from pymc3_hmm.distributions import HMMStateSeq, SwitchingProcess
from tests.utils import (
    gen_defualt_params_seaonality,
    time_series,
    simulate_poiszero_hmm,
)
from pymc3_hmm.step_methods import FFBSStep, TransMatConjugateStep
import pymc3 as pm
import theano.tensor as tt
import numpy as np
from datetime import datetime


def test_seasonality_sampling(N: int = 200, off_param=1):
    kwargs = gen_defualt_params_seaonality(N)
    simulation, _ = simulate_poiszero_hmm(**kwargs)

    with pm.Model() as test_model:
        p_0_rv = pm.Dirichlet("p_0", np.r_[1, 1, 1])
        p_1_rv = pm.Dirichlet("p_1", np.r_[1, 1, 1])
        p_2_rv = pm.Dirichlet("p_2", np.r_[1, 1, 1])

        P_tt = tt.stack([p_0_rv, p_1_rv, p_2_rv])
        P_rv = pm.Deterministic("P_tt", P_tt)

        pi_0_tt = simulation["pi_0"]
        y_test = simulation["Y_t"]

        S_rv = HMMStateSeq("S_t", y_test.shape[0], P_rv, pi_0_tt)
        S_rv.tag.test_value = (y_test > 0).astype(np.int)

        mu_1, mu_2 = [3000, 1000]

        E_1_mu, Var_1_mu = mu_1 * off_param, mu_1 / 5
        E_2_mu, Var_2_mu = (
            abs(mu_2 - mu_1) * off_param,
            abs(mu_2 - mu_1) * off_param / 5,
        )

        mu_1_rv = pm.Gamma("mu_1", E_1_mu ** 2 / Var_1_mu, E_1_mu / Var_1_mu)
        mu_2_rv = pm.Gamma("mu_2", E_2_mu ** 2 / Var_2_mu, E_2_mu / Var_2_mu)

        s = time_series(N)
        beta_s = pm.Gamma("beta_s", 1, 1, shape=(s.shape[1],))
        seasonal = tt.dot(s, beta_s)

        Y_rv = SwitchingProcess(
            "Y_t",
            [
                pm.Constant.dist(0),
                pm.Poisson.dist(E_1_mu * seasonal),
                pm.Poisson.dist((E_1_mu + E_2_mu) * seasonal),
            ],
            S_rv,
            observed=y_test,
        )
    with test_model:
        mu_step = pm.NUTS([mu_1_rv, mu_2_rv])
        ffbs = FFBSStep([S_rv])
        transitions = TransMatConjugateStep([p_0_rv, p_1_rv, p_2_rv], S_rv)
        steps = [ffbs, mu_step, transitions]
        start_time = datetime.now()
        trace_ = pm.sample(N, step=steps, return_inferencedata=True, chains=1)
        time_elapsed = datetime.now() - start_time
        y_trace = pm.sample_posterior_predictive(trace_.posterior)["Y_t"].mean(axis=0)

    st_trace = trace_.posterior["S_t"].mean(axis=0).mean(axis=0)
    mean_error_rate = (
        1 - np.sum(np.equal(st_trace, simulation["S_t"]) * 1) / len(simulation["S_t"])
    ).values.tolist()

    positive_index = simulation["Y_t"] > 0
    positive_sim = simulation["Y_t"][positive_index]
    MAPE = np.nanmean(abs(y_trace[positive_index] - positive_sim) / positive_sim)

    assert mean_error_rate < 0.05
    assert MAPE < 0.05
    return trace_, time_elapsed, test_model, simulation
