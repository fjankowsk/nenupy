"""

    Example :

    from nenupy.io.tf import Spectra
    sp = Spectra("/Users/aloh/Documents/Work/NenuFAR/Undisputed/JUPITER_TRACKING_20230527_083737_0.spectra")

"""

import numpy as np
import dask.array as da
from dask.diagnostics import ProgressBar
import astropy.units as u
from astropy.time import Time
from typing import Union, Tuple, List
import logging
log = logging.getLogger(__name__)

import nenupy.io.tf_utils as utils
from nenupy.beamlet import SData


BLOCK_HEADER = [
    ("idx", "uint64"), # first effective sample index used for this block
    ("TIMESTAMP", "uint64"), # TIMESTAMP of first sample used for this block
    ("BLOCKSEQNUMBER", "uint64"), # BLOCKSEQNUMBER of first sample used for this block
    ("fftlen", "int32"),  # fftlen : FFT length -> freq resolution= 0.1953125/fftlen MHz
    ("nfft2int", "int32"), # nfft2int : Nber of integrated FFTs -> time resolution= fftlen*nfft2int*5.12 us
    ("fftovlp", "int32"), # fftovlp : FFToverlap : 0 (for none) or fftlen/2
    ("apodisation", "int32"), # apodisation with 0 : none (01 to 99 : a generic K=1 cosine-sum window with coefficient 0.xx, 101 : hamming window, 102 : hann window)
    ("nffte", "int32"), # nffte : nber of FFTs to be read per beamlet within this block (so we have 'nffte' spectra/timesample per block)
    ("nbchan", "int32"), # nbchan : nber of subsequent beamlets/channels or nber of NenuFAR/LOFAR 195kHz beamlets, set to a NEGATIVE value when data packets lost ! (so we have 'fftlen*nbchan' frequencies for each spectra)
]

SUBBAND_WIDTH = 195312.5 * u.Hz


# ============================================================= #
# ----------------- _ProcessingConfiguration ------------------ #
class _ProcessingConfiguration:
    
    def __init__(self,
            time_min: Time,
            time_max: Time,
            frequency_min: u.Quantity,
            frequency_max: u.Quantity,
            available_beams: np.ndarray
        ):
        self.available_beams = available_beams
        self.time_min = time_min
        self.time_max = time_max
        self.frequency_min = frequency_min
        self.frequency_max = frequency_max

        self.time_range = Time([time_min.isot, time_max.isot], precision=max(time_min.precision, time_max.precision))
        self.frequency_range = [frequency_min.to_value(u.Hz), frequency_max.to_value(u.Hz)]*u.Hz
        self.beam = 0
        self.dispersion_measure = None
        self.rotation_measure = None
        self.rebin_dt = None
        self.rebin_df = None
        self.jump_correction = False
        self.dreambeam_inputs = (None, None, None)
        self.correct_bandpass = True
        self.edge_channels_to_remove = 0

    @property
    def beam(self) -> int:
        return self._beam
    @beam.setter
    def beam(self, selected_beam: int) -> None:
        if not isinstance(selected_beam, int):
            raise TypeError("Selected beam is expected as an integer value.")
        elif selected_beam not in self.available_beams:
            raise IndexError(f"Requested beam #{selected_beam} not found among available beam indices {self.available_beams}.")
        self._beam = selected_beam
        log.info(f"Beam #{self._beam} selected.")

    @property
    def time_range(self) -> Time:
        return self._time_range
    @time_range.setter
    def time_range(self, selected_range: Time):
        if not isinstance(selected_range, Time):
            raise TypeError("time_range expects an astropy.time.Time object.")
        if selected_range.size != 2:
            raise ValueError("time_range should be a length-2 Time array.")
        if selected_range[0] >= selected_range[1]:
            raise ValueError("time_range start >= stop.")
        if (selected_range[1] < self.time_min) or (selected_range[0] > self.time_max):
            log.warning("Requested time_range outside availaible data!")
        self._time_range = selected_range
        log.info(f"Time range set: {selected_range[0].isot} to {selected_range[1].isot}")

    @property
    def frequency_range(self) -> u.Quantity:
        return self._frequency_range
    @frequency_range.setter
    def frequency_range(self, selected_range: u.Quantity):
        if not isinstance(selected_range, u.Quantity):
            raise TypeError("frequency_range expects an astropy.units.Quantity object.")
        if selected_range.size != 2:
            raise ValueError("frequency_range should be a length-2 Quantity array.")
        if selected_range[0] >= selected_range[1]:
            raise ValueError("frequency_range min >= max.")
        self._frequency_range = selected_range
        log.info(f"Frequency range set: {selected_range[0].to(u.MHz)} to {selected_range[1].to(u.MHz)}")

    @property
    def edge_channels_to_remove(self) -> Union[int, Tuple[int, int]]:
        return self._edge_channels_to_remove
    @edge_channels_to_remove.setter
    def edge_channels_to_remove(self, channels: Union[int, Tuple[int, int]]):
        if isinstance(channels, tuple):
            if not len(channels) == 2:
                raise IndexError("If a `tuple` is given to the edge_channels_to_remove argument, it must be of length 2: (lower_edge_channels_to_remove, higher_edge_channels_to_remove).")
            elif not np.all([isinstance(chan, int) for chan in channels]):
                raise TypeError("Edge channels to remove muste be integers.")
        elif not isinstance(channels, int):
            raise TypeError("Edge channels to remove muste be integers.")
        self._edge_channels_to_remove = channels

# ============================================================= #
# -------------------------- Spectra -------------------------- #
class Spectra:

    def __init__(self, filename: str):
        log.info(f"\tReading {filename}...")
        self.filename = filename

        # Decode the main header and lazy load the data
        self._n_time_per_block = 0
        self.n_channels = 0
        self.n_subbands = 0
        self.dt = None
        self.df = None
        data = self._lazy_load_data()

        # Compute the boolean mask of bad blocks
        bad_block_mask = self._get_bad_data_mask(data)

        self._block_start_unix = data["TIMESTAMP"][~bad_block_mask] + data["BLOCKSEQNUMBER"][~bad_block_mask] / SUBBAND_WIDTH.to_value(u.Hz)
        self._subband_start_hz = data["data"]["channel"][0, :] * SUBBAND_WIDTH.to_value(u.Hz) # Assumed constant over time
        # Compute the frequency, time and beam axes
        # self.frequency_hz = utils.compute_spectra_frequencies(
        #     n_channels=self.n_channels,
        #     n_subbands=self.n_subbands,
        #     frequency_step_hz=self.df.to_value(u.Hz),
        #     channel_indices=data["data"]["channel"][0, :] # Assumed constant over time
        # )
        # self.time_unix = utils.compute_spectra_time(
        #     block_start_time_unix=data["TIMESTAMP"][~bad_block_mask] + data["BLOCKSEQNUMBER"][~bad_block_mask] / SUBBAND_WIDTH.to_value(u.Hz),
        #     ntime_per_block=self._n_time_per_block,
        #     time_step_s=self.dt.to_value(u.s)
        # )
        self.beam_indices_dict = utils.sort_beam_edges(
            beam_array=data["data"]["beam"][0], # Asummed same for all time step
            n_channels=self.n_channels,
        )

        # Transform the data in Dask Array, once correctly reshaped
        self.data = self._assemble_to_tf(data=data, mask=bad_block_mask)

        log.info("\tSetting up default configuration:")
        self.configuration = _ProcessingConfiguration(
            time_min=Time(self._block_start_unix[0], format="unix", precision=7),
            time_max=Time(self._block_start_unix[-1] + self._n_time_per_block * self.dt.to_value(u.s), format="unix", precision=7),
            frequency_min=self._subband_start_hz[0] * u.Hz,
            frequency_max=self._subband_start_hz[-1] * u.Hz + SUBBAND_WIDTH,
            available_beams=np.array(list(self.beam_indices_dict.keys())).astype(int)
        )

    # --------------------------------------------------------- #
    # --------------------- Getter/Setter --------------------- #
    @property
    def frequency_min(self) -> u.Quantity:
        freq_mins = []
        for _, boundaries in self.beam_indices_dict.items():
            freq_mins.append(self.frequency_hz[boundaries[0]])
        return np.min(freq_mins) * u.Hz
    
    @property
    def frequency_max(self) -> u.Quantity:
        freq_maxs = []
        for _, boundaries in self.beam_indices_dict.items():
            freq_maxs.append(self.frequency_hz[boundaries[1]])
        return np.max(freq_maxs) * u.Hz

    # --------------------------------------------------------- #
    # ------------------------ Methods ------------------------ #
    def get(self, stokes: Union[str, List[str]] = "I"):

        frequency_hz, time_unix, data = self._select_data()

        # Correct for the bandpass
        if self.configuration.correct_bandpass:
            log.info("Correcting for bandpass.")
            data = self._correct_bandpass(data=data, n_channels=self.n_channels)

        # Remove subband edge channels
        edge_chans = self.configuration.edge_channels_to_remove
        if edge_chans not in [0, (0, 0)]:
            log.info("\tRemoving edge channels...")
            data = self._remove_edge_channels(
                data=data,
                n_channels=self.n_channels,
                lower_edge_channels=edge_chans[0] if isinstance(edge_chans, tuple) else edge_chans,
                higher_edge_channels=edge_chans[1] if isinstance(edge_chans, tuple) else edge_chans,
            )

        data = utils.compute_stokes_parameters(data_array=data, stokes=stokes)

        frequency_hz, time_unix, data = self._time_frequency_rebin(
            data=data,
            times=time_unix,
            freqs=frequency_hz,
        )

        log.info("Computing the data...")
        with ProgressBar():
            data = data.compute()

        return SData(
            data=data,
            time=Time(time_unix, format="unix", precision=7),
            freq=frequency_hz*u.Hz,
            polar=stokes,
        )

    # --------------------------------------------------------- #
    # ----------------------- Internal ------------------------ #
    def _lazy_load_data(self) -> np.ndarray:

        # Read the header of the first block
        with open(self.filename, "rb") as rf:
            header_dtype = np.dtype(BLOCK_HEADER)
            header = np.frombuffer(
                rf.read(header_dtype.itemsize),
                count=1,
                dtype=header_dtype,
            )[0]
        self._n_time_per_block = header["nffte"]
        self.n_channels = header["fftlen"]
        self.n_subbands = np.abs(header["nbchan"]) # this could be negative

        # Fill in global attributes
        self.dt = (self.n_channels * header["nfft2int"] / SUBBAND_WIDTH).to(u.s)#* 5.12e-6 * u.s
        self.df = SUBBAND_WIDTH / self.n_channels #0.1953125 / self.n_channels * u.MHz

        # Deduce the structure of the full file
        beamlet_data_structure = (
            self._n_time_per_block,
            self.n_channels,
            2
        )
        beamlet_dtype = np.dtype(
            [
                ("lane", "int32"),
                ("beam", "int32"),
                ("channel", "int32"),
                ("fft0", "float32", beamlet_data_structure),
                ("fft1", "float32", beamlet_data_structure),
            ]
        )
        global_struct = BLOCK_HEADER + [("data", beamlet_dtype, (self.n_subbands))]

        # Open the file as a memory-mapped object
        with open(self.filename, "rb") as rf:
            tmp = np.memmap(rf, dtype="int8", mode="r")

        log.info(f"{self.filename} has been correctly parsed.")

        return tmp.view(np.dtype(global_struct))

    @staticmethod
    def _get_bad_data_mask(data: np.ndarray) -> np.ndarray:
        """ """

        log.info("\tChecking for missing data...")

        # Either the TIMESTAMP is set to 0, the first idx, or the SB number is negative
        # which indicates missing data. In all those cases we will ignore the associated data
        # since we cannot properly reconstruct the time ramp or the data themselves.
        block_timestamp_mask = data["TIMESTAMP"] == 0
        block_start_idx_mask = data["idx"] == 0
        block_nsubbands_mask = data["nbchan"] < 0

        # Computing the mask, setting the first index at non-zero since it should be the normal value.
        block_start_idx_mask[0] = False # Fake value, just to trick the mask
        bad_block_mask = block_start_idx_mask + block_start_idx_mask + block_nsubbands_mask

        log.info(f"There are {np.sum(bad_block_mask)}/{block_timestamp_mask.size} blocks containing missing data and/or wrong time information.")

        return bad_block_mask

    def _assemble_to_tf(self, data: np.ndarray, mask:  np.ndarray) -> da.Array:
        """ """
        # Transform the array in a Dask array, one chunk per block
        # Filter out the bad blocks
        data = da.from_array(
            data,
            chunks=(1,)
        )[~mask]

        # Convert the data to cross correlation electric field matrix
        # The data will be shaped like (n_block, n_subband, n_time_per_block, n_channels, 2, 2)
        data = utils.spectra_data_to_matrix(data["data"]["fft0"], data["data"]["fft1"])

        # Reshape the data into (time, frequency, 2, 2)
        data = utils.blocks_to_tf_data(
            data=data,
            n_block_times=self._n_time_per_block,
            n_channels=self.n_channels
        )

        return data

    def _select_data(self):
        """ """
        
        log.info("\tComputing the time selection...")
        tmin, tmax = self.configuration.time_range.unix
        n_blocks = self._block_start_unix.size

        # Find out which block indices are at the edges of the desired time range
        block_idx_min = int(np.argmin(np.abs(np.ceil(self._block_start_unix - tmin))))# n_blocks - np.argmax(((self._block_start_unix - tmin) <= 0)[::-1]) - 1
        block_idx_max = int(np.argmin(np.abs(np.ceil(self._block_start_unix - tmax))))#n_blocks - np.argmax(((self._block_start_unix - tmax) <= 0)[::-1]) - 1

        # Get the closest time index within each of the two bounding blocks
        dt_sec = self.dt.to_value(u.s)
        time_idx_min_in_block = int(np.round((tmin - self._block_start_unix[block_idx_min])/dt_sec))
        time_idx_min = block_idx_min * self._n_time_per_block + time_idx_min_in_block
        time_idx_max_in_block = int(np.round((tmax - self._block_start_unix[block_idx_max])/dt_sec))
        time_idx_max = block_idx_max * self._n_time_per_block + time_idx_max_in_block

        if time_idx_min == time_idx_max:
            log.warning("Time selection leads to empty dataset.")
            return None

        # Compute the time ramp between those blocks
        time_unix = utils.compute_spectra_time(
            block_start_time_unix=self._block_start_unix[block_idx_min:block_idx_max + 1],
            ntime_per_block=self._n_time_per_block,
            time_step_s=self.dt.to_value(u.s)
        )[time_idx_min_in_block:-(self._n_time_per_block - time_idx_max_in_block) + 1]

        log.info("\tComputing the frequency selection...")
        fmin, fmax = self.configuration.frequency_range.to_value(u.Hz)
        beam_idx_start, beam_idx_stop = self.beam_indices_dict[str(self.configuration.beam)]

        # Find out the subband edges covering the selected frequency range
        subbands_in_beam = self._subband_start_hz[int(beam_idx_start/self.n_channels):int((beam_idx_stop + 1)/self.n_channels)]
        sb_idx_min = int(np.argmin(np.abs(np.ceil(subbands_in_beam - fmin))))
        sb_idx_max = int(np.argmin(np.abs(np.ceil(subbands_in_beam - fmax))))

        # Select frequencies at the subband granularity at minimum
        # Later, we want to correct for bandpass, edge channels and so on...
        frequency_idx_min = sb_idx_min * self.n_channels
        frequency_idx_max = (sb_idx_max + 1) * self.n_channels
        frequency_hz = utils.compute_spectra_frequencies(
            subband_start_hz=subbands_in_beam[sb_idx_min:sb_idx_max + 1],
            n_channels=self.n_channels,
            frequency_step_hz=self.df.to_value(u.Hz)
        )

        selected_data = self.data[:, beam_idx_start:beam_idx_stop + 1, ...][time_idx_min:time_idx_max + 1, frequency_idx_min:frequency_idx_max, ...]

        return frequency_hz.compute(), time_unix.compute(), selected_data

    @staticmethod
    def _correct_bandpass(data: da.Array, n_channels: int) -> da.Array:
        """ """

        # Compute the bandpass
        bandpass = utils.get_bandpass(n_channels=n_channels)

        # Reshape the data array to isolate individual subbands
        n_times, n_freqs, _, _ = data.shape
        data = data.reshape(
            (
                n_times,
                int(n_freqs / n_channels), # subband
                n_channels, # channels
                2, 2
            )
        )

        # Multiply the channels by the bandpass to correct them
        data *= bandpass[None, None, :, None, None]

        # Re-reshape the data into time, frequency, (2, 2) array
        return data.reshape((n_times, n_freqs, 2, 2))

    @staticmethod
    def _remove_edge_channels(data: da.Array, n_channels: int, lower_edge_channels: int, higher_edge_channels: int) -> da.Array:
        """ """

        # Reshape the data array to isolate individual subbands
        n_times, n_freqs, _, _ = data.shape
        data = data.reshape(
            (
                n_times,
                int(n_freqs / n_channels), # subband
                n_channels, # channels
                2, 2
            )
        )

        # Set to NaN edge channels
        data[:, :, : lower_edge_channels, :, :] = np.nan # lower edge
        data[:, :, n_channels - higher_edge_channels :, :] = np.nan  # upper edge
        data = data.reshape((n_times, n_freqs, 2, 2))

        log.info(
            f"{lower_edge_channels} lower and {higher_edge_channels} higher "
            "band channels have been set to NaN at the subband edges."
        )

        return data

    def _time_frequency_rebin(self, data: da.Array, times: da.Array, freqs: da.Array) -> Tuple[da.Array, da.Array, da.Array]: 
        """ data: (time, frequency, ...)
        .. versionadded:: 1.1.0
        """

        ntimes_i, nfreqs_i, npols_i = data.shape

        if not (self.configuration.rebin_dt is None):
            # Rebin in time
            tbins = int(np.floor(self.configuration.rebin_dt / self.dt))
            log.info(f"Time-averaging {tbins} spectra, dt={tbins*self.dt}...")
            ntimes = int(np.floor(ntimes_i / tbins))
            tleftover = ntimes_i % ntimes
            log.info(f"Last {tleftover} spectra are left over for time-averaging.")
            data = data[: -tleftover if tleftover != 0 else ntimes_i, :, :].reshape(
                (ntimes, int((ntimes_i - tleftover) / ntimes), nfreqs_i, npols_i)
            )
            times = times[: -tleftover if tleftover != 0 else ntimes_i].reshape(
                (ntimes, int((ntimes_i - tleftover) / ntimes))
            )
            data = np.nanmean(data, axis=1)
            times = np.nanmean(times, axis=1)
            ntimes_i, nfreqs_i, npols_i = data.shape
            log.info("Data are time-averaged.")

        if not (self.configuration.rebin_df is None):
            # Rebin in frequency
            fbins = int(np.floor(self.configuration.rebin_df / self.df))
            log.info(f"Frequency-averaging {fbins} channels: df={fbins*self.df}...")
            nfreqs = int(np.floor(nfreqs_i / fbins))
            fleftover = nfreqs_i % nfreqs
            log.info(
                f"Last {fleftover} channels are left over for frequency-averaging."
            )
            data = data[:, : -fleftover if fleftover != 0 else nfreqs_i, :].reshape(
                (ntimes_i, nfreqs, int((nfreqs_i - fleftover) / nfreqs), npols_i)
            )
            freqs = freqs[: -fleftover if fleftover != 0 else nfreqs_i].reshape(
                (nfreqs, int((nfreqs_i - fleftover) / nfreqs))
            )
            data = np.nanmean(data, axis=2)
            freqs = np.nanmean(freqs, axis=1)
            log.info("Data are frequency-averaged.")

        return freqs, times, data 

