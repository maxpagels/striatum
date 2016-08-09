""" EXP4.P: An Extention to Exponential-weight algorithm for Exploration and Exploitation
This module contains a class that implements EXP4.P, a contextual bandit algorithm with expert advice.
"""

import logging
import six
from striatum.bandit.bandit import BaseBandit
import numpy as np
LOGGER = logging.getLogger(__name__)


class Exp4P(BaseBandit):

    """Exp4.P with pre-trained supervised learning algorithm.
    Parameters
    ----------
    actions : {array-like, None}
        Actions (arms) for recommendation
    historystorage: a HistoryStorage object
        The place where we store the histories of contexts and rewards.
    modelstorage: a ModelStorage object
        The place where we store the model parameters.
    models: the list of pre-trained supervised learning model objects.
        Use historical contents and rewards to train several multi-class classification models as experts.
        We strongly recommend to use scikit-learn package to pre-train the experts.
    delta: float, 0 < delta <= 1
        With probability 1 - delta, LinThompSamp satisfies the theoretical regret bound.
    pmin: float, 0 < pmin < 1/k
        The minimum probability to choose each action.
    Attributes
    ----------
    exp4p\_ : 'exp4p' object instance
        The contextual bandit algorithm instances
    References
    ----------
    .. [1]  Beygelzimer, Alina, et al. "Contextual bandit algorithms with supervised learning guarantees."
            International Conference on Artificial Intelligence and Statistics (AISTATS). 2011u.
    """

    def __init__(self, actions, historystorage, modelstorage, delta=0.1, pmin=None):
        super(Exp4P, self).__init__(historystorage, modelstorage, actions)
        self.models = models
        self.n_total = 0
        self.k = len(self._actions)          # number of actions (i.e. K in the paper)
        self.exp4p_ = None

        # delta > 0
        if not isinstance(delta, float):
            raise ValueError("delta should be float, the one"
                             "given is: %f" % pmin)
        self.delta = delta

        # p_min in [0, 1/k]
        if pmin is None:
            self.pmin = np.sqrt(np.log(10) / self.k / 10000)
        elif not isinstance(pmin, float):
            raise ValueError("pmin should be float, the one"
                             "given is: %f" % pmin)
        elif (pmin < 0) or (pmin > (1. / self.k)):
            raise ValueError("pmin should be in [0, 1/k], the one"
                             "given is: %f" % pmin)
        else:
            self.pmin = pmin

        # Initialize the model storage
        query_vector = np.zeros(self.k)     # probability distribution for action recommendation)
        w = {}              # weight vector for each expert
        advice = None
        self._modelstorage.save_model({'query_vector': query_vector, 'w': w, 'advice': advice})

    def exp4p(self):

        """The generator which implements the main part of Exp4.P.
        """

        while True:
            advice = yield
            advisors_id = advice.keys()

            w = self._modelstorage.get_model()['w']
            if w == {}:
                for i in advisors_id:
                    w[i] = 1
            w_sum = np.sum(w.values())

            query_vector = [(1 - self.k * self.pmin) *
                            np.sum(np.array([w[i] * advice[i][action_id] for i in advisors_id])/w_sum) +
                            self.pmin for action_id in self.actions_id]
            query_vector /= sum(query_vector)
            self._modelstorage.save_model({'query_vector': query_vector, 'w': w, 'advice': advice})

            estimated_reward = {}
            uncertainty = {}
            score = {}
            for i in range(self.k):
                estimated_reward[self._actions_id[i]] = query_vector[i]
                uncertainty[self._actions_id[i]] = 0
                score[self._actions_id[i]] = query_vector[i]
            yield estimated_reward, uncertainty, score

        raise StopIteration

    def get_action(self, context=None, n_action=1, advice=None):
        """Return the action to perform

            Parameters
            ----------
            context : {array-like, None}
                The context of current state, None if no context available.

            n_action: int
                Number of actions wanted to recommend users.

            advice: dictionary
                The advice vectors from othe experts, {expert_id: advice_vectors}, where advice_vectors is
                a dictionary {action_id: probability} predicted probability for each action.

            Returns
            -------
            history_id : int
                The history id of the action.

            action : list of dictionaries
                In each dictionary, it will contains {rank: Action object, estimated_reward, uncertainty}

        """

        if self.exp4p_ is None:
            self.exp4p_ = self.exp4p()
            six.next(self.exp4p_)
            estimated_reward, uncertainty, score = self.exp4p_.send(advice)
        else:
            six.next(self.exp4p_)
            estimated_reward, uncertainty, score = self.exp4p_.send(advice)

        action_recommend = []
        actions_recommend_id = np.random.choice(self._actions_id, size=n_action, p=score, replace=False)

        for action_id in actions_recommend_id:
            action_id = int(action_id)
            action = [action for action in self._actions if action.action_id == action_id][0]
            action_recommend.append({'action': action, 'estimated_reward': estimated_reward[action_id],
                                     'uncertainty': uncertainty[action_id], 'score': score[action_id]})

        self.n_total += 1
        history_id = self._historystorage.add_history(context, action_recommend, reward=None)
        return history_id, action_recommend

    def reward(self, history_id, reward):
        """Reward the preivous action with reward.

        Parameters
        ----------
        history_id : int
            The history id of the action to reward.

        reward : dictionary
            The dictionary {action_id, reward}, where reward is a float.
        """

        w_old = self._modelstorage.get_model()['w']
        query_vector = self._modelstorage.get_model()['query_vector']
        advice = self._modelstorage.get_model()['advice']

        # Update the model
        w_new = {}
        for action_id, reward_tmp in reward.items():
            rhat = [{i: 0} for i in self._actions_id]
            rhat[action_id] = reward_tmp/query_vector[action_id]
            yhat = [np.dot(advice[i], rhat.values()) for i in advice.keys()]
            vhat = [sum([advice[i][action_id]/query_vector for action_id in self._actions_id]) for i in advice.keys()]
            for i in advice.keys():
                w_new[i] = w_old[i] + np.exp(self.pmin / 2 * (
                    yhat[i] + vhat[i] * np.sqrt(
                        np.log(len(advice) / self.delta) / self.k / self.n_total
                        )
                    )
                )

        self._modelstorage.save_model({'query_vector': query_vector, 'w': w_new, 'advice': advice})

        # Update the history
        self._historystorage.add_reward(history_id, reward)

    def add_action(self, actions):
        """ Add new actions (if needed).

            Parameters
            ----------
            actions : list
                Actions (arms) for recommendation
        """
        actions_id = [actions[i].action_id for i in range(len(actions))]
        self._actions.extend(actions)
        self._actions_id.extend(actions_id)
