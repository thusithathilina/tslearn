"""
The :mod:`tslearn.barycenters` module gathers algorithms for time series
barycenter computation.
"""

# Code for soft DTW is by Mathieu Blondel under Simplified BSD license

import numpy
from scipy.interpolate import interp1d
from scipy.optimize import minimize
from sklearn.exceptions import ConvergenceWarning
import warnings

from tslearn.utils import to_time_series_dataset, check_equal_size, \
    to_time_series, ts_size
from tslearn.preprocessing import TimeSeriesResampler
from tslearn.metrics import dtw_path, SquaredEuclidean, SoftDTW


__author__ = 'Romain Tavenard romain.tavenard[at]univ-rennes2.fr'


def _set_weights(w, n):
    """Return w if it is a valid weight vector of size n, and a vector of n 1s
    otherwise.
    """
    if w is None or len(w) != n:
        w = numpy.ones((n, ))
    return w


def euclidean_barycenter(X, weights=None):
    """Standard Euclidean barycenter computed from a set of time series.

    Parameters
    ----------
    X : array-like, shape=(n_ts, sz, d)
        Time series dataset.

    weights: None or array
        Weights of each X[i]. Must be the same size as len(X).
        If None, uniform weights are used.

    Returns
    -------
    numpy.array of shape (sz, d)
        Barycenter of the provided time series dataset.

    Notes
    -----
        This method requires a dataset of equal-sized time series

    Examples
    --------
    >>> time_series = [[1, 2, 3, 4], [1, 2, 4, 5]]
    >>> bar = euclidean_barycenter(time_series)
    >>> bar.shape
    (4, 1)
    >>> bar
    array([[1. ],
           [2. ],
           [3.5],
           [4.5]])
    """
    X_ = to_time_series_dataset(X)
    weights = _set_weights(weights, X_.shape[0])
    return numpy.average(X_, axis=0, weights=weights)


def _init_avg(X, barycenter_size):
    if X.shape[1] == barycenter_size:
        return numpy.nanmean(X, axis=0)
    else:
        X_avg = numpy.nanmean(X, axis=0)
        xnew = numpy.linspace(0, 1, barycenter_size)
        f = interp1d(numpy.linspace(0, 1, X_avg.shape[0]), X_avg,
                     kind="linear", axis=0)
        return f(xnew)


def _petitjean_assignment(X, barycenter, metric_params=None):
    if metric_params is None:
        metric_params = {}
    n = X.shape[0]
    barycenter_size = barycenter.shape[0]
    assign = ([[] for _ in range(barycenter_size)],
              [[] for _ in range(barycenter_size)])
    for i in range(n):
        path, _ = dtw_path(X[i], barycenter, **metric_params)
        for pair in path:
            assign[0][pair[1]].append(i)
            assign[1][pair[1]].append(pair[0])
    return assign


def _petitjean_update_barycenter(X, assign, barycenter_size, weights):
    barycenter = numpy.zeros((barycenter_size, X.shape[-1]))
    for t in range(barycenter_size):
        barycenter[t] = numpy.average(X[assign[0][t], assign[1][t]], axis=0,
                                      weights=weights[assign[0][t]])
    return barycenter


def _petitjean_cost(X, barycenter, assign, weights):
    cost = 0.
    barycenter_size = barycenter.shape[0]
    for t_barycenter in range(barycenter_size):
        for i_ts, t_ts in zip(assign[0][t_barycenter],
                              assign[1][t_barycenter]):
            sq_norm = numpy.linalg.norm(X[i_ts, t_ts] -
                                        barycenter[t_barycenter]) ** 2
            cost += weights[i_ts] * sq_norm
    return cost / weights.sum()


def dtw_barycenter_averaging_petitjean(X, barycenter_size=None,
                                       init_barycenter=None,
                                       max_iter=30, tol=1e-5, weights=None,
                                       metric_params=None,
                                       verbose=False):
    """DTW Barycenter Averaging (DBA) method.

    DBA was originally presented in [1]_.
    This implementation is not the one documented in the API, but is kept
    in the codebase to check the documented one for non-regression.

    Parameters
    ----------
    X : array-like, shape=(n_ts, sz, d)
        Time series dataset.

    barycenter_size : int or None (default: None)
        Size of the barycenter to generate. If None, the size of the barycenter
        is that of the data provided at fit
        time or that of the initial barycenter if specified.

    init_barycenter : array or None (default: None)
        Initial barycenter to start from for the optimization process.

    max_iter : int (default: 30)
        Number of iterations of the Expectation-Maximization optimization
        procedure.

    tol : float (default: 1e-5)
        Tolerance to use for early stopping: if the decrease in cost is lower
        than this value, the
        Expectation-Maximization procedure stops.

    weights: None or array
        Weights of each X[i]. Must be the same size as len(X).
        If None, uniform weights are used.

    metric_params: dict or None (default: None)
        DTW constraint parameters to be used.
        See :ref:`tslearn.metrics.dtw_path <fun-tslearn.metrics.dtw_path>` for
        a list of accepted parameters
        If None, no constraint is used for DTW computations.

    verbose : boolean (default: False)
        Whether to print information about the cost at each iteration or not.

    Returns
    -------
    numpy.array of shape (barycenter_size, d) or (sz, d) if barycenter_size \
            is None
        DBA barycenter of the provided time series dataset.

    Examples
    --------
    >>> time_series = [[1, 2, 3, 4], [1, 2, 4, 5]]
    >>> dtw_barycenter_averaging_petitjean(time_series, max_iter=5)
    array([[1. ],
           [2. ],
           [3.5],
           [4.5]])
    >>> time_series = [[1, 2, 3, 4], [1, 2, 3, 4, 5]]
    >>> dtw_barycenter_averaging_petitjean(time_series, max_iter=5)
    array([[1. ],
           [2. ],
           [3. ],
           [4. ],
           [4.5]])
    >>> dtw_barycenter_averaging_petitjean(time_series, max_iter=5,
    ...                          metric_params={"itakura_max_slope": 2})
    array([[1. ],
           [2. ],
           [3. ],
           [3.5],
           [4.5]])
    >>> dtw_barycenter_averaging_petitjean(time_series, max_iter=5,
    ...                                    barycenter_size=3)
    array([[1.5       ],
           [3.        ],
           [4.33333333]])
    >>> dtw_barycenter_averaging_petitjean([[0, 0, 0], [10, 10, 10]],
    ...                                    weights=numpy.array([0.75, 0.25]))
    array([[2.5],
           [2.5],
           [2.5]])

    References
    ----------
    .. [1] F. Petitjean, A. Ketterlin & P. Gancarski. A global averaging method
       for dynamic time warping, with applications to clustering. Pattern
       Recognition, Elsevier, 2011, Vol. 44, Num. 3, pp. 678-693
    """
    X_ = to_time_series_dataset(X)
    if barycenter_size is None:
        barycenter_size = X_.shape[1]
    weights = _set_weights(weights, X_.shape[0])
    if init_barycenter is None:
        barycenter = _init_avg(X_, barycenter_size)
    else:
        barycenter_size = init_barycenter.shape[0]
        barycenter = init_barycenter
    cost_prev, cost = numpy.inf, numpy.inf
    for it in range(max_iter):
        assign = _petitjean_assignment(X_, barycenter, metric_params)
        cost = _petitjean_cost(X_, barycenter, assign, weights)
        if verbose:
            print("[DBA] epoch %d, cost: %.3f" % (it + 1, cost))
        barycenter = _petitjean_update_barycenter(X_, assign, barycenter_size,
                                                  weights)
        if abs(cost_prev - cost) < tol:
            break
        elif cost_prev < cost:
            warnings.warn("DBA loss is increasing while it should not be. "
                          "Stopping optimization.", ConvergenceWarning)
            break
        else:
            cost_prev = cost
    return barycenter


def _mm_assignment(X, barycenter, weights, metric_params=None):
    """Computes item assignement based on DTW alignments and return cost as a
    bonus.

    Parameters
    ----------
    X : numpy.array of shape (n, sz, d)
        Time-series to be averaged

    barycenter : numpy.array of shape (barycenter_size, d)
        Barycenter as computed at the current step of the algorithm.

    weights: array
        Weights of each X[i]. Must be the same size as len(X).

    metric_params: dict or None (default: None)
        DTW constraint parameters to be used.
        See :ref:`tslearn.metrics.dtw_path <fun-tslearn.metrics.dtw_path>` for
        a list of accepted parameters
        If None, no constraint is used for DTW computations.

    Returns
    -------
    list of index pairs
        Warping paths

    float
        Current alignment cost
    """
    if metric_params is None:
        metric_params = {}
    n = X.shape[0]
    cost = 0.
    list_p_k = []
    for i in range(n):
        path, dist_i = dtw_path(barycenter, X[i], **metric_params)
        cost += dist_i ** 2 * weights[i]
        list_p_k.append(path)
    cost /= weights.sum()
    return list_p_k, cost


def _mm_valence_warping(list_p_k, barycenter_size, weights):
    """Compute Valence and Warping matrices from paths.

    Valence matrices are denoted :math:`V^{(k)}` and Warping matrices are
    :math:`W^{(k)}` in [1]_.

    This function returns the sum of :math:`V^{(k)}` diagonals (as a vector)
    and a list of :math:`W^{(k)}` matrices.

    Parameters
    ----------
    list_p_k : list of index pairs
        Warping paths

    barycenter_size : int
        Size of the barycenter to generate.

    weights: array
        Weights of each X[i]. Must be the same size as len(X).

    Returns
    -------
    numpy.array of shape (barycenter_size, )
        sum of weighted :math:`V^{(k)}` diagonals (as a vector)

    list of numpy.array of shape (barycenter_size, sz_k)
        list of weighted :math:`W^{(k)}` matrices

    References
    ----------

    .. [1] D. Schultz and B. Jain. Nonsmooth Analysis and Subgradient Methods
       for Averaging in Dynamic Time Warping Spaces.
       Pattern Recognition, 74, 340-358.
    """
    diag_sum_v_k = numpy.zeros((barycenter_size, ))
    list_w_k = []
    for k, p_k in enumerate(list_p_k):
        sz_k = p_k[-1][1] + 1
        w_k = numpy.zeros((barycenter_size, sz_k))
        for i, j in p_k:
            w_k[i, j] = 1.
        list_w_k.append(w_k * weights[k])
        diag_sum_v_k += w_k.sum(axis=1) * weights[k]
    return diag_sum_v_k, list_w_k


def _mm_update_barycenter(X, diag_sum_v_k, list_w_k):
    """Update barycenters using the formula from Algorithm 2 in [1]_.

    Parameters
    ----------
    X : numpy.array of shape (n, sz, d)
        Time-series to be averaged

    diag_sum_v_k : numpy.array of shape (barycenter_size, )
        sum of weighted :math:`V^{(k)}` diagonals (as a vector)

    list_w_k : list of numpy.array of shape (barycenter_size, sz_k)
        list of weighted :math:`W^{(k)}` matrices

    Returns
    -------
    numpy.array of shape (barycenter_size, d)
        Updated barycenter

    References
    ----------

    .. [1] D. Schultz and B. Jain. Nonsmooth Analysis and Subgradient Methods
       for Averaging in Dynamic Time Warping Spaces.
       Pattern Recognition, 74, 340-358.
    """
    d = X.shape[2]
    barycenter_size = diag_sum_v_k.shape[0]
    sum_w_x = numpy.zeros((barycenter_size, d))
    for k, (w_k, x_k) in enumerate(zip(list_w_k, X)):
        sum_w_x += w_k.dot(x_k[:ts_size(x_k)])
    barycenter = numpy.diag(1. / diag_sum_v_k).dot(sum_w_x)
    return barycenter


def dtw_barycenter_averaging(X, barycenter_size=None, init_barycenter=None,
                             max_iter=30, tol=1e-5, weights=None,
                             metric_params=None,
                             verbose=False):
    """DTW Barycenter Averaging (DBA) method.

    DBA was originally presented in [1]_.
    This implementation is based on a idea from [2]_ (Majorize-Minimize Mean
    Algorithm).

    Parameters
    ----------
    X : array-like, shape=(n_ts, sz, d)
        Time series dataset.

    barycenter_size : int or None (default: None)
        Size of the barycenter to generate. If None, the size of the barycenter
        is that of the data provided at fit
        time or that of the initial barycenter if specified.

    init_barycenter : array or None (default: None)
        Initial barycenter to start from for the optimization process.

    max_iter : int (default: 30)
        Number of iterations of the Expectation-Maximization optimization
        procedure.

    tol : float (default: 1e-5)
        Tolerance to use for early stopping: if the decrease in cost is lower
        than this value, the
        Expectation-Maximization procedure stops.

    weights: None or array
        Weights of each X[i]. Must be the same size as len(X).
        If None, uniform weights are used.

    metric_params: dict or None (default: None)
        DTW constraint parameters to be used.
        See :ref:`tslearn.metrics.dtw_path <fun-tslearn.metrics.dtw_path>` for
        a list of accepted parameters
        If None, no constraint is used for DTW computations.

    verbose : boolean (default: False)
        Whether to print information about the cost at each iteration or not.

    Returns
    -------
    numpy.array of shape (barycenter_size, d) or (sz, d) if barycenter_size \
            is None
        DBA barycenter of the provided time series dataset.

    Examples
    --------
    >>> time_series = [[1, 2, 3, 4], [1, 2, 4, 5]]
    >>> dtw_barycenter_averaging(time_series, max_iter=5)
    array([[1. ],
           [2. ],
           [3.5],
           [4.5]])
    >>> time_series = [[1, 2, 3, 4], [1, 2, 3, 4, 5]]
    >>> dtw_barycenter_averaging(time_series, max_iter=5)
    array([[1. ],
           [2. ],
           [3. ],
           [4. ],
           [4.5]])
    >>> dtw_barycenter_averaging(time_series, max_iter=5,
    ...                          metric_params={"itakura_max_slope": 2})
    array([[1. ],
           [2. ],
           [3. ],
           [3.5],
           [4.5]])
    >>> dtw_barycenter_averaging(time_series, max_iter=5, barycenter_size=3)
    array([[1.5       ],
           [3.        ],
           [4.33333333]])
    >>> dtw_barycenter_averaging([[0, 0, 0], [10, 10, 10]], max_iter=1,
    ...                          weights=numpy.array([0.75, 0.25]))
    array([[2.5],
           [2.5],
           [2.5]])

    References
    ----------
    .. [1] F. Petitjean, A. Ketterlin & P. Gancarski. A global averaging method
       for dynamic time warping, with applications to clustering. Pattern
       Recognition, Elsevier, 2011, Vol. 44, Num. 3, pp. 678-693

    .. [2] D. Schultz and B. Jain. Nonsmooth Analysis and Subgradient Methods
       for Averaging in Dynamic Time Warping Spaces.
       Pattern Recognition, 74, 340-358.
    """
    X_ = to_time_series_dataset(X)
    if barycenter_size is None:
        barycenter_size = X_.shape[1]
    weights = _set_weights(weights, X_.shape[0])
    if init_barycenter is None:
        barycenter = _init_avg(X_, barycenter_size)
    else:
        barycenter_size = init_barycenter.shape[0]
        barycenter = init_barycenter
    cost_prev, cost = numpy.inf, numpy.inf
    for it in range(max_iter):
        list_p_k, cost = _mm_assignment(X_, barycenter, weights, metric_params)
        diag_sum_v_k, list_w_k = _mm_valence_warping(list_p_k, barycenter_size,
                                                     weights)
        if verbose:
            print("[DBA] epoch %d, cost: %.3f" % (it + 1, cost))
        barycenter = _mm_update_barycenter(X_, diag_sum_v_k, list_w_k)
        if abs(cost_prev - cost) < tol:
            break
        elif cost_prev < cost:
            warnings.warn("DBA loss is increasing while it should not be. "
                          "Stopping optimization.", ConvergenceWarning)
            break
        else:
            cost_prev = cost
    return barycenter


def _softdtw_func(Z, X, weights, barycenter, gamma):
    # Compute objective value and grad at Z.

    Z = Z.reshape(barycenter.shape)
    G = numpy.zeros_like(Z)
    obj = 0

    for i in range(len(X)):
        D = SquaredEuclidean(Z, X[i])
        sdtw = SoftDTW(D, gamma=gamma)
        value = sdtw.compute()
        E = sdtw.grad()
        G_tmp = D.jacobian_product(E)
        G += weights[i] * G_tmp
        obj += weights[i] * value

    return obj, G.ravel()


def softdtw_barycenter(X, gamma=1.0, weights=None, method="L-BFGS-B", tol=1e-3,
                       max_iter=50, init=None):
    """Compute barycenter (time series averaging) under the soft-DTW geometry.

    Parameters
    ----------
    X : array-like, shape=(n_ts, sz, d)
        Time series dataset.
    gamma: float
        Regularization parameter.
        Lower is less smoothed (closer to true DTW).
    weights: None or array
        Weights of each X[i]. Must be the same size as len(X).
        If None, uniform weights are used.
    method: string
        Optimization method, passed to `scipy.optimize.minimize`.
        Default: L-BFGS.
    tol: float
        Tolerance of the method used.
    max_iter: int
        Maximum number of iterations.
    init: array or None (default: None)
        Initial barycenter to start from for the optimization process.
        If `None`, euclidean barycenter is used as a starting point.

    Returns
    -------
    numpy.array of shape (bsz, d) where `bsz` is the size of the `init` array \
            if provided or `sz` otherwise
        Soft-DTW barycenter of the provided time series dataset.

    Examples
    --------
    >>> time_series = [[1, 2, 3, 4], [1, 2, 4, 5]]
    >>> softdtw_barycenter(time_series, max_iter=5)
    array([[1.25161574],
           [2.03821705],
           [3.5101956 ],
           [4.36140605]])
    >>> time_series = [[1, 2, 3, 4], [1, 2, 3, 4, 5]]
    >>> softdtw_barycenter(time_series, max_iter=5)
    array([[1.21349933],
           [1.8932251 ],
           [2.67573269],
           [3.51057026],
           [4.33645802]])
    """
    X_ = to_time_series_dataset(X)
    weights = _set_weights(weights, X_.shape[0])
    if init is None:
        if check_equal_size(X_):
            barycenter = euclidean_barycenter(X_, weights)
        else:
            resampled_X = TimeSeriesResampler(sz=X_.shape[1]).fit_transform(X_)
            barycenter = euclidean_barycenter(resampled_X, weights)
    else:
        barycenter = init

    if max_iter > 0:
        X_ = numpy.array([to_time_series(d, remove_nans=True) for d in X_])

        def f(Z):
            return _softdtw_func(Z, X_, weights, barycenter, gamma)

        # The function works with vectors so we need to vectorize barycenter.
        res = minimize(f, barycenter.ravel(), method=method, jac=True, tol=tol,
                       options=dict(maxiter=max_iter, disp=False))
        return res.x.reshape(barycenter.shape)
    else:
        return barycenter
