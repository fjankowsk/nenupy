#! /usr/bin/python3
# -*- coding: utf-8 -*-


r"""
    .. _schedule_constraints:

    ***********************
    Observation constraints
    ***********************

    Automatic scheduling of astronomical observations relies on
    the definition of constraints that govern identification of
    optimal time periods to observe a given celestial target.
    The different classes implemented in the 
    :mod:`~nenupy.schedule.constraints` module allow for an easy
    way of specifying these constraints.

    Each :class:`~nenupy.schedule.constraints.Constraint` object
    is `callable` and requires an argument of type
    :class:`~nenupy.schedule.targets.ESTarget` or 
    :class:`~nenupy.schedule.targets.SSTarget` in order to evaluate
    the constraint's 'score' over a given time range.
    
    In the following, an instance of :class:`~nenupy.schedule.targets.ESTarget`
    is initialized for the source *Cygnus A* and stored in the variable
    ``target``. The method :meth:`~nenupy.schedule.targets._Target.computePosition`
    is called to compute all astronomical properties at the
    location of `NenuFAR <https://nenufar.obs-nancay.fr/en/astronomer/>`_
    for the time-range ``times``.

    .. code-block:: python
        :emphasize-lines: 3,8,9

        >>> from astropy.time import Time, TimeDelta
        >>> import numpy as np
        >>> from nenupy.schedule import ESTarget

        >>> dt = TimeDelta(3600, format='sec')
        >>> times = Time('2021-01-01 00:00:00') + np.arange(24)*dt

        >>> target = ESTarget.fromName('Cas A')
        >>> target.computePosition(times)


    .. seealso::
        :class:`~nenupy.schedule.targets.ESTarget` or 
        :class:`~nenupy.schedule.targets.ESTarget` objects are
        described in :ref:`schedule_targets` in more details.


    Single constraint
    -----------------

    There are several constraints that could be defined (see
    :ref:`constraints_summary`). The simplest and probably most
    basic one is the 'elevation constraint' (embedded in the 
    :class:`~nenupy.schedule.constraints.ElevationCnst` class) since
    observing at :math:`e > 0^\circ` is a necessary requirement
    for a ground-based observatory.
    Once the constraint has been evaluated on ``target``,
    a normalized 'score' is returned and can be plotted using the
    :meth:`~nenupy.schedule.constraints.Constraint.plot` method.
    
    .. code-block:: python

        >>> from nenupy.schedule import ElevationCnst

        >>> c = ElevationCnst()
        >>> score = c(target)
        >>> c.plot()


    .. image:: ./_images/elevconstraint_casa0deg.png
        :width: 800

    If the required elevation to perform a good-quality observation
    needs to be greater than a given value, it could be specified
    to the :attr:`~nenupy.schedule.constraints.ElevationCnst.elevationMin`
    attribute.

    .. code-block:: python

        >>> c = ElevationCnst(elevationMin=40)
        >>> score = c(target)
        >>> c.plot()


    .. image:: ./_images/elevconstraint_casa40deg.png
        :width: 800

    The :class:`~nenupy.schedule.constraints.ElevationCnst`'s score is
    now at :math:`0` whenever the ``target`` elevation is lower than
    :attr:`~nenupy.schedule.constraints.ElevationCnst.elevationMin`.


    Multiple constraints
    --------------------
    
    Several constraints are often needed to select an appropriate
    time window for a given observation. The
    :class:`~nenupy.schedule.constraints.Constraints` class is by
    default initialized with ``ElevationCnst(elevationMin=0)``, but
    any other constraint may be passed as arguments:
    
    .. code-block:: python

        >>> from nenupy.schedule import (
                ESTarget,
                Constraints,
                ElevationCnst,
                MeridianTransitCnst,
                LocalTimeCnst
            )
        >>> from astropy.time import Time, TimeDelta
        >>> from astropy.coordinates import SkyCoord, Angle

        >>> dts = np.arange(24+1)*TimeDelta(3600, format='sec')
        >>> times = Time('2021-01-01 00:00:00') + dts
        >>> target = ESTarget.fromName('Cas A')
        >>> target.computePosition(times)

        >>> cnst = Constraints(
                ElevationCnst(elevationMin=20, weight=3),
                MeridianTransitCnst(),
                LocalTimeCnst(Angle(12, 'hour'), Angle(4, 'hour'))
            )
        
        >>> cnst.evaluate(target, times)
        
        >>> cnst.plot()

    .. image:: ./_images/sch_constraints.png
        :width: 800

    .. _constraints_summary:

    Constraint classes
    ------------------

    .. autosummary::

        ~nenupy.schedule.constraints.Constraints
        ~nenupy.schedule.constraints.ElevationCnst
        ~nenupy.schedule.constraints.MeridianTransitCnst
        ~nenupy.schedule.constraints.AzimuthCnst
        ~nenupy.schedule.constraints.LocalTimeCnst
        ~nenupy.schedule.constraints.TimeRangeCnst


    .. inheritance-diagram:: nenupy.schedule.constraints
        :parts: 3


"""


__author__ = 'Alan Loh'
__copyright__ = 'Copyright 2021, nenupy'
__credits__ = ['Alan Loh']
__maintainer__ = 'Alan'
__email__ = 'alan.loh@obspm.fr'
__status__ = 'Production'
__all__ = [
    'Constraint',
    'TargetConstraint',
    'ScheduleConstraint',
    'ElevationCnst',
    'MeridianTransitCnst',
    'AzimuthCnst',
    'LocalTimeCnst',
    'TimeRangeCnst',
    'Constraints'
]


import numpy as np
from astropy.time import Time, TimeDelta
from astropy.coordinates import Angle
import pytz
import matplotlib.pyplot as plt

from nenupy.schedule.targets import _Target

import logging
log = logging.getLogger(__name__)


# ============================================================= #
# ------------------------ Constraint ------------------------- #
# ============================================================= #
class Constraint(object):
    """ Base class for all the constraint definitions.

        .. warning::
            :class:`~nenupy.schedule.constraints.Constraint`
            should not be used on its own.

        .. versionadded:: 1.2.0
    """

    def __init__(self, weight=1):
        self.score = 1
        self.weight = weight


    def __call__(self, *arg):
        """ Test de docstring
        """
        if not hasattr(self, '_evaluate'):
            raise AttributeError(
                '<Constraint> should not be used on its own.'
            )
        return self._evaluate(*arg)

    
    def __str__(self):
        """
        """
        return f'{self.__class__}'


    # --------------------------------------------------------- #
    # --------------------- Getter/Setter --------------------- #
    @property
    def weight(self):
        """
        """
        return self._weight
    @weight.setter
    def weight(self, w):
        if not isinstance(w, (float, int)):
            raise TypeError(
                '<weight> should be a number.'
            )
        elif w <= 0:
            raise ValueError(
                '<weight> should be > 0.'
            )
        self._weight = w
    

    # --------------------------------------------------------- #
    # ------------------------ Methods ------------------------ #
    def plot(self, **kwargs):
        """ Plots the constraint's score previously evaluated.

            :param figSize:
                Size of the figure. Default: ``(10, 5)``.
            :type figSize:
                `tuple`
            :param figName:
                Name of the figure to be stored. Default: ``''``,
                the figure is only displayed.
            :type figName:
                `str`
            :param marker:
                Plot marker type (see :func:`matplotlib.pyplot.plot`).
                Default: ``'.'``.
            :type marker:
                `str`
            :param linestyle:
                Plot line style (see :func:`matplotlib.pyplot.plot`).
                Default: ``':'``
            :type linestyle:
                `str`
            :param linewidth:
                Plot line width (see :func:`matplotlib.pyplot.plot`).
                Default: ``1``
            :type linewidth:
                `int` or `float`
        """
        fig = plt.figure(
            figsize=kwargs.get('figsize', (10, 5))
        )
        self._plotConstraint(**kwargs)
        plt.xlabel('Time index')
        plt.ylabel('Constraint score')
        plt.title(f'{self.__class__}')

        # Save or show the figure
        figName = kwargs.get('figName', '')
        if figName != '':
            plt.savefig(
                figName,
                dpi=300,
                bbox_inches='tight',
                transparent=True
            )
            log.info(f"Figure '{figName}' saved.")
        else:
            plt.show()
        plt.close('all')


    # --------------------------------------------------------- #
    # ----------------------- Internal ------------------------ #
    def _plotConstraint(self, **kwargs):
        """ Internal method to plot a single constraint without
            initializing the figure object.
        """
        plt.plot(
            np.where(
                np.isnan(self.score),
                0,
                self.score
            ),
            marker=kwargs.get('marker', '.'),
            linestyle=kwargs.get('linestyle', ':'),
            linewidth=kwargs.get('linewidth', 1),
            label=f'{self.__class__}'
        )


    @staticmethod
    def _isArray(arr):
        """ Check that arr is a genuine numpy array.
        """
        if not isinstance(arr, np.ndarray):
            raise TypeError(
                f'{np.ndarray.__class__} object expected.'
            )
# ============================================================= #
# ============================================================= #


# ============================================================= #
# --------------------- TargetConstraint ---------------------- #
# ============================================================= #
class TargetConstraint(Constraint):
    """ Base class for constraints involving target propertiy checks.

        .. warning::
            :class:`~nenupy.schedule.constraints.TargetConstraint`
            should not be used on its own.

        .. versionadded:: 1.2.0
    """

    def __init__(self, weight):
        super().__init__(weight=weight)


    # --------------------------------------------------------- #
    # ----------------------- Internal ------------------------ #
    @staticmethod
    def _isTarget(target):
        """
        """
        if not isinstance(target, _Target):
            raise TypeError(
                f'{_Target.__class__} object expected.'
            )


    @staticmethod
    def _checkAngle(angle):
        """
        """
        if not isinstance(angle, Angle):
            angle = Angle(angle, unit='deg')
        return angle
# ============================================================= #
# ============================================================= #


# ============================================================= #
# -------------------- ScheduleConstraint --------------------- #
# ============================================================= #
class ScheduleConstraint(Constraint):
    """ Base class for constraints involving time range checks.

        .. warning::
            :class:`~nenupy.schedule.constraints.ScheduleConstraint`
            should not be used on its own.

        .. versionadded:: 1.2.0
    """

    def __init__(self, weight):
        super().__init__(weight=weight)


    # --------------------------------------------------------- #
    # ----------------------- Internal ------------------------ #
    @staticmethod
    def _isTime(time):
        """
        """
        if not isinstance(time, Time):
            raise TypeError(
                f'{Time.__class__} object expected.'
            )
# ============================================================= #
# ============================================================= #


# ============================================================= #
# ----------------------- ElevationCnst ----------------------- #
# ============================================================= #
class ElevationCnst(TargetConstraint):
    """ Elevation constraint

        :param elevationMin:
            Target's elevation below which the constraint score
            is null. If provided as a dimensionless quantity,
            the value is interpreted as degrees.
        :type elevationMin:
            `int`, `float`, or :class:`~astropy.coordinates.Angle`
        :param weight:
            Weight of the constraint. Allows to ponderate each
            constraint with respect to each other if
            :class:`~nenupy.schedule.constraint.ElevationCnst`
            is included in :class:`~nenupy.schedule.constraint.Constraints`
            for instance.
        :type weight:
            `int` or `float`

        .. versionadded:: 1.2.0
    """

    def __init__(self, elevationMin=0., weight=1):
        super().__init__(weight=weight)
        self.elevationMin = elevationMin


    # --------------------------------------------------------- #
    # --------------------- Getter/Setter --------------------- #
    @property
    def elevationMin(self):
        """ Minimal elevation required to perform an observation.

            :type: `float` or :class:`~astropy.coordinates.Angle`
        """
        return self._elevationMin
    @elevationMin.setter
    def elevationMin(self, emin):
        emin = self._checkAngle(emin)
        if (emin.deg < 0.) or (emin.deg > 90):
            raise ValueError(
                f'`elevationMin`={emin.deg} deg must fall '
                'between 0 and 90 degrees.'
            )
        self._elevationMin = emin


    # --------------------------------------------------------- #
    # ------------------------ Methods ------------------------ #
    def getScore(self, indices):
        r""" Computes the :class:`~nenupy.schedule.constraint.ElevationCnst`'s
            score for the given ``indices``.

            The score is computed as:

            .. math::
                {\rm score} = \left\langle \frac{\mathbf{e}(t)}{{\rm max}(\mathbf{e})} \right\rangle_{\rm indices}
            
            where :math:`\mathbf{e}(t)` is the elevation of the
            target (set to :math:`0` whenever it is lower than
            :attr:`~nenupy.schedule.constraints.ElevationCnst.elevationMin`).

            :param indices:
                Indices of :class:`~nenupy.schedule.constraint.Constraint.score`
                on which the score will be evaluated.
            :type indices:
                :class:`~numpy.ndarray`

            :returns:
                Constraint score.
            :rtype: `float`
        """
        # aboveMin = self.score[indices] > 0
        # return np.mean(self.score[indices][aboveMin])
        # return np.mean(self.score[indices])
        return np.mean(
            np.where(
                np.isnan(self.score[indices]),
                0,
                self.score[indices]
            )
        )


    # --------------------------------------------------------- #
    # ----------------------- Internal ------------------------ #
    def _evaluate(self, target):
        """ Evaluates the constraint :class:`~nenupy.schedule.constraint.ElevationCnst`
            on the ``target`` which astronomical positions need
            to be computed first (using :meth:`~nenupy.schedule.targets._Target.computePosition`).

            :param target:
                Target for which :class:`~nenupy.schedule.constraint.ElevationCnst`
                should be evaluated.
            :type target: :class:`~nenupy.schedule.targets._Target`

            :returns:
                Constraint's score.
            :rtype: :class:`~numpy.ndarray`
        """
        self._isTarget(target)

        elevation = target.elevation.deg
        elevMean = (elevation[1:] + elevation[:-1])/2
        # elevMean[elevMean <= self.elevationMin.deg] = 0.
        elevMean[elevMean <= self.elevationMin.deg] = np.nan
        # if elevMax == 0.:
        if all(np.isnan(elevMean)):
            log.warning(
                "Constraint <ElevationConstraint(elevationMin="
                f"{self.elevationMin})> evaluated for target "
                f"'{target.target}' cannot be satisfied over the "
                "given time range."
            )
            # self.score = elevation[1:]*0.
            self.score = elevation[1:]*np.nan
        else:
            elevMax = np.nanmax(elevMean)
            self.score = elevMean/elevMax
        return self.score
# ============================================================= #
# ============================================================= #


# ============================================================= #
# -------------------- MeridianTransitCnst -------------------- #
# ============================================================= #
class MeridianTransitCnst(TargetConstraint):
    """ Meridian Transit constraint

        .. versionadded:: 1.2.0
    """

    def __init__(self, weight=1):
        super().__init__(weight=weight)


    # --------------------------------------------------------- #
    # ------------------------ Methods ------------------------ #
    def getScore(self, indices):
        r""" Computes the :class:`~nenupy.schedule.constraint.MeridianTransitCnst`'s
            score for the given ``indices``.

            Returns 1 if the merdian transit is within the indices

            The score is computed as:

            .. math::
                {\rm score} = \begin{cases}
                    1, t_{\rm transit} \in \mathbf{t}({\rm indices})\\
                    0, t_{\rm transit} \notin \mathbf{t}({\rm indices})
                \end{cases}
            
            where :math:`t_{\rm transit}` is the meridian transit time
            and :math:`\mathbf{t}` is the time range on which the
            target positions are computed.

            :param indices:
                Indices of :class:`~nenupy.schedule.constraint.Constraint.score`
                on which the score will be evaluated.
            :type indices:
                :class:`~numpy.ndarray`

            :returns:
                Constraint score.
            :rtype: `float`
        """
        self._isArray(indices)
        return np.sum(self.score[indices], axis=-1)


    # --------------------------------------------------------- #
    # ----------------------- Internal ------------------------ #
    def _evaluate(self, target):
        self._isTarget(target)

        hourAngle = target.hourAngle
        transitIdx = np.where(
            (np.roll(hourAngle, -1) - hourAngle)[:-1] < 0
        )[0]

        # Set transit slots to maximal score
        scores = np.zeros(hourAngle.size)
        scores[transitIdx] = 1.
        self.score = scores[:-1]
        return self.score
# ============================================================= #
# ============================================================= #


# ============================================================= #
# ------------------------ AzimuthCnst ------------------------ #
# ============================================================= #
class AzimuthCnst(TargetConstraint):
    """
        .. versionadded:: 1.2.0
    """

    def __init__(self, azimuth, weight=1):
        super().__init__(weight=weight)
        self.azimuth = azimuth


    # --------------------------------------------------------- #
    # --------------------- Getter/Setter --------------------- #
    @property
    def azimuth(self):
        """
        """
        return self._azimuth
    @azimuth.setter
    def azimuth(self, az):
        az = self._checkAngle(az)
        if (az.deg < 0.) or (az.deg > 360):
            raise ValueError(
                f'`azimuth`={az.deg} deg must fall '
                'between 0 and 360 degrees.'
            )
        self._azimuth = az


    # --------------------------------------------------------- #
    # ------------------------ Methods ------------------------ #
    def getScore(self, indices):
        """
        """
        self._isArray(indices)
        return np.sum(self.score[indices], axis=-1)


    # --------------------------------------------------------- #
    # ----------------------- Internal ------------------------ #
    def _evaluate(self, target):
        self._isTarget(target)
        
        azimuths = target.azimuth.rad
        az = self.azimuth.rad
        
        if target.isCircumpolar:
            complexAzStarts = np.angle(
                np.cos(azimuths[:-1]) + 1j*np.sin(azimuths[:-1])
            )
            complexAzStops = np.angle(
                np.cos(azimuths[1:]) + 1j*np.sin(azimuths[1:])
            )

            mask = (az >= complexAzStarts) &\
                (az <= complexAzStops)
            mask |= (az <= complexAzStarts) &\
                (az >= complexAzStops)
        else:
            mask = (az >= azimuths[:-1]) &\
                (az <= azimuths[1:])
        
        self.score = mask.astype(float)
        return self.score
# ============================================================= #
# ============================================================= #


# ============================================================= #
# ----------------------- LocalTimeCnst ----------------------- #
# ============================================================= #
class LocalTimeCnst(ScheduleConstraint):
    """
        .. versionadded:: 1.2.0
    """

    def __init__(self, hMin, hMax, weight=1):
        super().__init__(weight=weight)
        self.hMin = hMin
        self.hMax = hMax


    # --------------------------------------------------------- #
    # --------------------- Getter/Setter --------------------- #
    @property
    def hMin(self):
        """
        """
        return self._hMin
    @hMin.setter
    def hMin(self, h):
        if not isinstance(h, Angle):
            raise TypeError(
                f'{h} should be of type {type(Angle)}.'
            )
        self._hMin = h


    @property
    def hMax(self):
        """
        """
        return self._hMax
    @hMax.setter
    def hMax(self, h):
        if not isinstance(h, Angle):
            raise TypeError(
                f'{h} should be of type {type(Angle)}.'
            )
        self._hMax = h


    # --------------------------------------------------------- #
    # ------------------------ Methods ------------------------ #
    def getScore(self, indices):
        """
        """
        self._isArray(indices)
        return np.mean(self.score[indices], axis=-1)


    # --------------------------------------------------------- #
    # ----------------------- Internal ------------------------ #
    def _evaluate(self, time):
        """
        """
        self._isTime(time)
        
        # Convert time to France local time (take into account
        # daylight savings)
        tz = pytz.timezone('Europe/Paris')
        timezoneTime = map(tz.localize, time.datetime)
        utcOffset = np.array(
            [tt.utcoffset().total_seconds() for tt in timezoneTime]
        )
        localTime = time + TimeDelta(utcOffset, format='sec')
        
        # Convert the 'hour' part in decimal 'angle' values
        hours = np.array([tt.split()[1] for tt in localTime.iso])
        localHours = Angle(hours, unit='hour').hour

        # Selection
        if self.hMin > self.hMax:
            # If 'midnight' is in the range
            mask = (localHours <= self.hMin.hour) &\
                (localHours >= self.hMax.hour)
            mask = ~mask
        else:
            mask = (localHours >= self.hMin.hour) &\
                (localHours <= self.hMax.hour)
        score = mask[:-1].astype(float)
        self.score = np.where(score==0, np.nan, score)
        return self.score
# ============================================================= #
# ============================================================= #


# ============================================================= #
# ----------------------- TimeRangeCnst ----------------------- #
# ============================================================= #
class TimeRangeCnst(ScheduleConstraint):
    """
        .. versionadded:: 1.2.0
    """

    def __init__(self, tMin, tMax, weight=1):
        super().__init__(weight=weight)
        self.tMin = tMin
        self.tMax = tMax


    # --------------------------------------------------------- #
    # --------------------- Getter/Setter --------------------- #
    @property
    def tMin(self):
        """
        """
        return self._tMin
    @tMin.setter
    def tMin(self, t):
        if not isinstance(t, Time):
            raise TypeError(
                f'{t} should be of type {type(Time)}.'
            )
        self._tMin = t


    @property
    def tMax(self):
        """
        """
        return self._tMax
    @tMax.setter
    def tMax(self, t):
        if not isinstance(t, Time):
            raise TypeError(
                f'{t} should be of type {type(Time)}.'
            )
        self._tMax = t


    # --------------------------------------------------------- #
    # ------------------------ Methods ------------------------ #
    def getScore(self, indices):
        """
        """
        self._isArray(indices)
        return np.mean(self.score[indices], axis=-1)


    # --------------------------------------------------------- #
    # ----------------------- Internal ------------------------ #
    def _evaluate(self, time):
        """ time: dim + 1
        """
        self._isTime(time)
        
        jds = time.jd
        
        mask = (jds >= self.tMin.jd) & (jds <= self.tMax.jd)
        score = mask[:-1].astype(float)
        self.score = np.where(score==0, np.nan, score)
        return self.score
# ============================================================= #
# ============================================================= #


# ============================================================= #
# ------------------------ Constraints ------------------------ #
# ============================================================= #
class Constraints(object):
    """
        .. versionadded:: 1.2.0
    """

    def __init__(self, *constraints):
        self._default_el = False
        self.constraints = constraints
        self.score = 1
        
        # Check they are all of unique type
        unique, count = np.unique(
            [str(cons.__class__) for cons in self.constraints],
            return_counts=True
        )
        if any(count > 1):
            message = (
                'There can only be one constraint type per '
                'observation:'
            )
            for typ, n in zip(unique, count):
                if n > 1:
                    message += f"\n\t* '{typ}': {n} instances."
            raise ValueError(message)

        # Add the elevation constraint by default
        if not str(ElevationCnst) in unique:
            self.constraints += (ElevationCnst(0.),)
            self._default_el = True


    def __add__(self, other):
        """
        """
        if not isinstance(other, Constraint):
            raise TypeError('')

        if isinstance(other, ElevationCnst):
            if self._default_el:
                # Remove the default elevation constraint
                # if a new one is added
                cs = np.array([str(c.__class__) for c in self.constraints])
                elCnst_idx = np.where(cs == str(ElevationCnst))[0][0]
                listCnst = list(self.constraints) 
                listCnst.pop(elCnst_idx) 
                self.constraints = tuple(listCnst)
                self._default_el = False
        
        constraints = self.constraints + (other,)
        cts = Constraints(*constraints)
        cts._default_el = self._default_el
        return cts


    def __getitem__(self, n):
        """
        """
        return self.constraints[n]


    def __len__(self):
        """
        """
        return len(self.constraints)


    # --------------------------------------------------------- #
    # --------------------- Getter/Setter --------------------- #
    @property
    def size(self):
        """
        """
        return len(self)


    @property
    def weights(self):
        """
        """
        return np.array([cnt.weight for cnt in self])
    


    # --------------------------------------------------------- #
    # ------------------------ Methods ------------------------ #
    def evaluate(self, target, time, method='prod'):
        """
            method: [prod, sum]
        """
        cnts = np.zeros((self.size, time.size - 1))
        for i, cnt in enumerate(self):
            if isinstance(cnt, TargetConstraint):
                cnts[i, :] = cnt(target)
            elif isinstance(cnt, ScheduleConstraint):
                cnts[i, :] = cnt(time)
            else:
                pass
        score = np.average(cnts, weights=self.weights, axis=0)
        self.score = np.where(
            np.isnan(score),
            0,
            score
        )
        return self.score


    def plot(self, **kwargs):
        """
            kwargs:
                figsize
                figName

        """
        fig = plt.figure(
            figsize=kwargs.get('figsize', (10, 5))
        )
        for cnt in self:
            # Overplot each constraint
            cnt._plotConstraint(**kwargs)

        plt.plot(
            self.score,
            label='Total'
        )

        plt.xlabel('Time index')
        plt.ylabel('Constraint score')
        plt.legend()

        # Save or show the figure
        figName = kwargs.get('figName', '')
        if figName != '':
            plt.savefig(
                figName,
                dpi=300,
                bbox_inches='tight',
                transparent=True
            )
            log.info(f"Figure '{figName}' saved.")
        else:
            plt.show()
        plt.close('all')

    # --------------------------------------------------------- #
    # ----------------------- Internal ------------------------ #
# ============================================================= #
# ============================================================= #


