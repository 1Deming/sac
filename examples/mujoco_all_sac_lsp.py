import argparse
import os

import tensorflow as tf
import numpy as np

from rllab.envs.normalized_env import normalize
from rllab.envs.mujoco.gather.ant_gather_env import AntGatherEnv
from rllab.envs.mujoco.swimmer_env import SwimmerEnv
from rllab.envs.mujoco.ant_env import AntEnv
from rllab.envs.mujoco.humanoid_env import HumanoidEnv
from rllab.misc.instrument import VariantGenerator

from sac.algos import SAC
from sac.envs import (
    GymEnv,
    MultiDirectionSwimmerEnv,
    MultiDirectionAntEnv,
    MultiDirectionHumanoidEnv,
    RandomGoalSwimmerEnv,
    RandomGoalAntEnv,
    RandomGoalHumanoidEnv,

    RandomWallAntEnv,
    CrossMazeAntEnv
)

from sac.misc.instrument import run_sac_experiment
from sac.misc.utils import timestamp, unflatten
from sac.policies import LatentSpacePolicy
from sac.replay_buffers import SimpleReplayBuffer
from sac.value_functions import NNQFunction, NNVFunction
from sac.preprocessors import MLPPreprocessor
from .variants import parse_domain_and_task, get_variants

ENVIRONMENTS = {
    'swimmer': {
        'default': SwimmerEnv,
        'multi-direction': MultiDirectionSwimmerEnv,
    },
    'ant': {
        'default': AntEnv,
        'multi-direction': MultiDirectionAntEnv,
        'cross-maze': CrossMazeAntEnv
    },
    'humanoid': {
        'default': HumanoidEnv,
        'multi-direction': MultiDirectionHumanoidEnv,
    },
    'random-wall-ant': {
        'prefix': 'random-wall-ant-env',
        'env_name': 'random-wall-ant',

        'epoch_length': 1000,
        'max_path_length': 1000,
        'n_epochs': int(1e4 + 1),
        'scale_reward': 10.0,

        'preprocessing_hidden_sizes': (128, 128, 16),
        'policy_s_t_units': 8,

        'snapshot_gap': 1000,
    },
    'simple-maze-ant-env': {  # 21 DoF
        'prefix': 'simple-maze-ant-env',
        'env_name': 'simple-maze-ant',

        'epoch_length': 1000,
        'max_path_length': 1000,
        'n_epochs': int(10e3 + 1),
        'scale_reward': 10,

        'preprocessing_hidden_sizes': (128, 128, 16),
        'policy_s_t_units': 8,
        'policy_fix_h_on_reset': True,

        'snapshot_gap': 2000,

        # 'env_reward_type': ['dense'],
        # 'discount': [0.99],
        # 'env_terminate_at_goal': False,
        # 'env_goal_reward_weight': [0.1, 0.3, 1, 3],

        'env_reward_type': ['sparse'],
        'discount': [0.99, 0.999],
        'env_terminate_at_goal': True,
        'env_goal_reward_weight': [100, 300, 1000],

        'env_goal_radius': 2,
        'env_velocity_reward_weight': 1,
        'env_ctrl_cost_coeff': 0, # 1e-2,
        'env_contact_cost_coeff': 0, # 1e-3,
        'env_survive_reward': 0, # 5e-2,
        'env_goal_distance': np.linalg.norm([6,-6]),
        'env_goal_angle_range': (0, 2*np.pi),
    },
    'ant-gather-env': {  # 21 DoF
        'prefix': 'ant-gather-env',
        'env_name': 'ant-gather-env',

        'epoch_length': 1000,
        'max_path_length': 1000,
        'n_epochs': int(30e3 + 1),
        'scale_reward': [100, 300, 1000, 3000, 10000],

        'preprocessing_hidden_sizes': (128, 128, 16),
        'policy_s_t_units': 8,
        'policy_fix_h_on_reset': [False],

        'snapshot_gap': 2000,

        'discount': [0.99],
        'control_interval': [1],

        'env_activity_range': 6, # 20, # 6
        'env_sensor_range': 6, # 20, # 6
        'env_n_bombs': 8, # 40, # 8
        'env_n_apples': 8, # 40, # 8
        'env_sensor_span': 2*np.pi,

        'env_coef_inner_rew': lambda scale_reward: [10.0 / scale_reward],
        'env_dying_cost': 0,
    },
}

DEFAULT_DOMAIN = 'swimmer'
AVAILABLE_DOMAINS = set(ENVIRONMENTS.keys())
AVAILABLE_TASKS = set(y for x in ENVIRONMENTS.values() for y in x.values())

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--domain',
                        type=str,
                        choices=AVAILABLE_DOMAINS,
                        default=DEFAULT_DOMAIN)
    parser.add_argument('--task',
                        type=str,
                        choices=AVAILABLE_TASKS,
                        default='default')
    parser.add_argument('--env', type=str, default=DEFAULT_ENV)
    parser.add_argument('--exp_name', type=str, default=timestamp())
    parser.add_argument('--mode', type=str, default='local')
    parser.add_argument('--log_dir', type=str, default=None)
    args = parser.parse_args()

    return args

def run_experiment(variant):
    env_params = variant['env_params']
    policy_params = variant['policy_params']
    value_fn_params = variant['value_fn_params']
    algorithm_params = variant['algorithm_params']
    replay_buffer_params = variant['replay_buffer_params']

    task = variant['task']
    domain = variant['domain']

    env = normalize(ENVIRONMENTS[domain][task](**env_params))

    pool = SimpleReplayBuffer(env_spec=env.spec, **replay_buffer_params)

    base_kwargs = algorithm_params['base_kwargs']

    M = value_fn_params['layer_size']
    qf = NNQFunction(env_spec=env.spec, hidden_layer_sizes=(M, M))
    vf = NNVFunction(env_spec=env.spec, hidden_layer_sizes=(M, M))

    nonlinearity = {
        None: None,
        'relu': tf.nn.relu,
        'tanh': tf.nn.tanh
    }[policy_params['preprocessing_output_nonlinearity']]

    preprocessing_hidden_sizes = policy_params.get('preprocessing_hidden_sizes')
    if preprocessing_hidden_sizes is not None:
        observations_preprocessor = MLPPreprocessor(
            env_spec=env.spec,
            layer_sizes=preprocessing_hidden_sizes,
            output_nonlinearity=nonlinearity)
    else:
        observations_preprocessor = None

    policy_s_t_layers = policy_params['s_t_layers']
    policy_s_t_units = policy_params['s_t_units']
    s_t_hidden_sizes = [policy_s_t_units] * policy_s_t_layers

    bijector_config = {
        'scale_regularization': policy_params['scale_regularization'],
        'num_coupling_layers': policy_params['coupling_layers'],
        'translation_hidden_sizes': s_t_hidden_sizes,
        'scale_hidden_sizes': s_t_hidden_sizes,
    }

    policy = LatentSpacePolicy(
        env_spec=env.spec,
        mode="train",
        squash=True,
        bijector_config=bijector_config,
        observations_preprocessor=observations_preprocessor)

    algorithm = SAC(
        base_kwargs=base_kwargs,
        env=env,
        policy=policy,
        pool=pool,
        qf=qf,
        vf=vf,
        lr=algorithm_params['lr'],
        scale_reward=algorithm_params['scale_reward'],
        discount=algorithm_params['discount'],
        tau=algorithm_params['tau'],
        target_update_interval=algorithm_params['target_update_interval'],
        save_full_state=False,
    )

    tf_utils.get_default_session().run(tf.global_variables_initializer())

    algorithm.train()


def launch_experiments(variant_generator, args):
    variants = variant_generator.variants()
    # TODO: Remove unflatten. Our variant generator should support nested params
    variants = [unflatten(variant, separator='.') for variant in variants]

    num_experiments = len(variants)
    print('Launching {} experiments.'.format(num_experiments))

    for i, variant in enumerate(variants):
        print("Experiment: {}/{}".format(i, num_experiments))
        run_params = variant['run_params']

        experiment_prefix = variant['prefix'] + '/' + args.exp_name
        experiment_name = '{prefix}-{exp_name}-{i:02}'.format(
            prefix=variant['prefix'], exp_name=args.exp_name, i=i)

        run_sac_experiment(
            run_experiment,
            mode=args.mode,
            variant=variant,
            exp_prefix=experiment_prefix,
            exp_name=experiment_name,
            n_parallel=1,
            seed=run_params['seed'],
            terminate_machine=True,
            log_dir=args.log_dir,
            snapshot_mode=run_params['snapshot_mode'],
            snapshot_gap=run_params['snapshot_gap'],
            sync_s3_pkl=run_params['sync_pkl'],
        )


def main():
    args = parse_args()

    domain, task = args.domain, args.task
    if (not domain) or (not task):
        domain, task = parse_domain_and_task(args.env)

    variant_generator = get_variants(domain=domain, task=task, policy='lsp')
    launch_experiments(variant_generator, args)


if __name__ == '__main__':
    main()
