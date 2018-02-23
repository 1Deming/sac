import argparse
import os

import tensorflow as tf
import numpy as np

from rllab.envs.normalized_env import normalize
from rllab.misc.instrument import VariantGenerator

from sac.algos import SACV2
from sac.envs import (
    GymEnv,
    MultiDirectionSwimmerEnv,
    MultiDirectionAntEnv,
    MultiDirectionHumanoidEnv,
    RandomGoalSwimmerEnv,
    RandomGoalAntEnv,
    RandomGoalHumanoidEnv,
)
from sac.misc.instrument import run_sac_experiment
from sac.misc.utils import timestamp
from sac.policies import RealNVPPolicy
from sac.replay_buffers import SimpleReplayBuffer
from sac.value_functions import NNQFunction, NNVFunction
from sac.preprocessors import MLPPreprocessor

try:
    import git
    repo = git.Repo(os.getcwd())
    git_rev = repo.active_branch.commit.name_rev
except:
    git_rev = None

COMMON_PARAMS = {
    'seed': [10, 11, 12, 13, 14],
    'lr': 3e-4,
    'policy_lr': 3e-4,
    'discount': 0.99,
    'target_update_interval': 1,
    'tau': 1e-2,
    'layer_size': 128,
    'batch_size': 128,
    'max_pool_size': 1e6,
    'n_train_repeat': 1,
    'epoch_length': 1000,
    'snapshot_mode': 'gap',
    'snapshot_gap': 1000,
    'sync_pkl': True,

    # real nvp configs
    'policy_coupling_layers': 2,
    'policy_s_t_layers': 1,
    'policy_scale_regularization': 0.0,
    'preprocessing_hidden_sizes': None,
    'preprocessing_output_nonlinearity': 'relu',

    'git_sha': git_rev
}
ENV_PARAMS = {
    'multi-direction-swimmer': {  # 2 DoF
        'prefix': 'multi-direction-swimmer',
        'env_name': 'multi-direction-swimmer',
        'epoch_length': 1000,
        'max_path_length': 1000,
        'n_epochs': int(5e2 + 1),
        'scale_reward': 100.0,
        # if using 'scale_reward': 'piecewise_constant'
        # 'scale_reward_boundaries': (100,),
        # 'scale_reward_values': (100.0, 10.0),

        'preprocessing_hidden_sizes': (128, 128, 4),
        'policy_s_t_units': 2,
        'snapshot_gap': 100
    },
    'random-goal-swimmer': {  # 2 DoF
        'prefix': 'random-goal-swimmer',
        'env_name': 'random-goal-swimmer',
        'epoch_length': 1000,
        'max_path_length': 1000,
        'n_epochs': int(5e3 + 1),
        'scale_reward': 100.0,

        'preprocessing_hidden_sizes': (128, 128, 4),
        'policy_s_t_units': 2,

        'snapshot_gap': 500,

        'env_reward_type': ['dense'],
        'env_terminate_at_goal': False,
        'env_goal_reward_weight': 3e-1,
        'env_goal_radius': 0.25,
        'env_goal_distance': 5,
        'env_goal_angle_range': (-0.25*np.pi, 0.25*np.pi),
    },

    'multi-direction-ant': {  # 8 DoF
        'prefix': 'multi-direction-ant',
        'env_name': 'multi-direction-ant',
        'epoch_length': 1000,
        'max_path_length': 1000,
        'n_epochs': int(1e4 + 1),
        'scale_reward': 3.0,

        'preprocessing_hidden_sizes': (128, 128, 16),
        'policy_s_t_units': 8,

        'snapshot_gap': 1000,
    },
    'random-goal-ant': {  # 8 DoF
        'prefix': 'random-goal-ant',
        'env_name': 'random-goal-ant',
        'epoch_length': 1000,
        'max_path_length': 1000,
        'n_epochs': int(1e5 + 1),
        'scale_reward': 3.0,

        'preprocessing_hidden_sizes': (128, 128, 16),
        'policy_s_t_units': 8,

        'snapshot_gap': 1000,

        'env_reward_type': ['dense'],
        'env_terminate_at_goal': False,
        'env_goal_reward_weight': 3e-1,
        'env_goal_radius': 0.25,
        'env_goal_distance': 25,
        'env_goal_angle_range': (0, 2*np.pi),
    },

    'multi-direction-humanoid': {  # 21 DoF
        'prefix': 'multi-direction-humanoid',
        'env_name': 'multi-direction-humanoid',
        'epoch_length': 1000,
        'max_path_length': 1000,
        'n_epochs': int(2e4 + 1),
        'scale_reward': 3.0,

        'preprocessing_hidden_sizes': (128, 128, 42),
        'policy_s_t_units': 21,

        'snapshot_gap': 2000,
    },
    'random-goal-humanoid': {  # 21 DoF
        'prefix': 'random-goal-humanoid',
        'env_name': 'random-goal-humanoid',
        'epoch_length': 1000,
        'max_path_length': 1000,
        'n_epochs': int(2e5 + 1),
        'scale_reward': 3.0,

        'preprocessing_hidden_sizes': (128, 128, 42),
        'policy_s_t_units': 21,

        'snapshot_gap': 4000,

        'env_reward_type': ['dense'],
        'env_terminate_at_goal': False,
        'env_goal_reward_weight': 3e-1,
        'env_goal_radius': 0.25,
        'env_goal_distance': 5,
        'env_goal_angle_range': (0, 2*np.pi),
    },
}

DEFAULT_ENV = 'swimmer'
AVAILABLE_ENVS = list(ENV_PARAMS.keys())


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--env', type=str, choices=AVAILABLE_ENVS, default=DEFAULT_ENV)
    parser.add_argument('--exp_name', type=str, default=timestamp())
    parser.add_argument('--mode', type=str, default='local')
    parser.add_argument('--log_dir', type=str, default=None)
    args = parser.parse_args()

    return args


def get_variants(args):
    env_params = ENV_PARAMS[args.env]
    params = COMMON_PARAMS
    params.update(env_params)

    vg = VariantGenerator()
    for key, val in params.items():
        if isinstance(val, list):
            vg.add(key, val)
        else:
            vg.add(key, [val])

    return vg


MULTI_DIRECTION_ENVS = {
    'swimmer': MultiDirectionSwimmerEnv,
    'ant': MultiDirectionAntEnv,
    'humanoid': MultiDirectionHumanoidEnv,
}

RANDOM_GOAL_ENVS = {
    'swimmer': RandomGoalSwimmerEnv,
    'ant': RandomGoalAntEnv,
    'humanoid': RandomGoalHumanoidEnv,
}

def run_experiment(variant):
    env_name = variant['env_name']
    env_type = env_name.split('-')[-1]

    if 'multi-direction' in env_name:
        EnvClass = MULTI_DIRECTION_ENVS[env_type]
        env = normalize(EnvClass())
    elif 'random-goal' in env_name:
        EnvClass = RANDOM_GOAL_ENVS[env_type]
        env_args = {
            name.replace('env_', '', 1): value
            for name, value in variant.items()
            if name.startswith('env_') and name != 'env_name'
        }
        env = normalize(EnvClass(**env_args))

    pool = SimpleReplayBuffer(
        env_spec=env.spec,
        max_replay_buffer_size=variant['max_pool_size'],
    )

    base_kwargs = dict(
        min_pool_size=variant['max_path_length'],
        epoch_length=variant['epoch_length'],
        n_epochs=variant['n_epochs'],
        max_path_length=variant['max_path_length'],
        batch_size=variant['batch_size'],
        n_train_repeat=variant['n_train_repeat'],
        eval_render=False,
        eval_n_episodes=1,
        eval_deterministic=True,
    )

    M = variant['layer_size']
    qf = NNQFunction(
        env_spec=env.spec,
        hidden_layer_sizes=[M, M],
    )

    vf = NNVFunction(
        env_spec=env.spec,
        hidden_layer_sizes=[M, M],
    )

    nonlinearity = {
        None: None,
        'relu': tf.nn.relu,
        'tanh': tf.nn.tanh
    }[variant['preprocessing_output_nonlinearity']]

    preprocessing_hidden_sizes = variant.get('preprocessing_hidden_sizes')
    if preprocessing_hidden_sizes is not None:
        observations_preprocessor = MLPPreprocessor(
            env_spec=env.spec,
            layer_sizes=preprocessing_hidden_sizes,
            output_nonlinearity=nonlinearity)
    else:
        observations_preprocessor = None

    policy_s_t_layers = variant['policy_s_t_layers']
    policy_s_t_units = variant['policy_s_t_units']
    s_t_hidden_sizes = [policy_s_t_units] * policy_s_t_layers

    real_nvp_config = {
        "scale_regularization": variant['policy_scale_regularization'],
        "num_coupling_layers": variant['policy_coupling_layers'],
        "translation_hidden_sizes": s_t_hidden_sizes,
        "scale_hidden_sizes": s_t_hidden_sizes,
    }

    policy = RealNVPPolicy(
        env_spec=env.spec,
        mode="train",
        squash=True,
        real_nvp_config=real_nvp_config,
        observations_preprocessor=observations_preprocessor)

    if variant['scale_reward'] == 'piecewise_constant':
        boundaries = variant['scale_reward_boundaries']
        values = variant['scale_reward_values']
        scale_reward = lambda iteration: (
            tf.train.piecewise_constant(iteration, boundaries, values))
    else:
        scale_reward = variant['scale_reward']

    algorithm = SACV2(
        base_kwargs=base_kwargs,
        env=env,
        policy=policy,
        pool=pool,
        qf=qf,
        vf=vf,
        lr=variant['lr'],
        policy_lr=variant['policy_lr'],
        scale_reward=scale_reward,
        discount=variant['discount'],
        tau=variant['tau'],
        target_update_interval=variant['target_update_interval'],
        save_full_state=False,
    )

    algorithm.train()


def launch_experiments(variant_generator, args):
    variants = variant_generator.variants()

    num_experiments = len(variants)
    print('Launching {} experiments.'.format(num_experiments))

    for i, variant in enumerate(variants):
        print("Experiment: {}/{}".format(i, num_experiments))
        experiment_prefix = variant['prefix'] + '/' + args.exp_name
        experiment_name = (
            variant['prefix'] + '-' + args.exp_name + '-' + str(i).zfill(2))

        run_sac_experiment(
            run_experiment,
            mode=args.mode,
            variant=variant,
            exp_prefix=experiment_prefix,
            exp_name=experiment_name,
            n_parallel=1,
            seed=variant['seed'],
            terminate_machine=True,
            log_dir=args.log_dir,
            snapshot_mode=variant['snapshot_mode'],
            snapshot_gap=variant['snapshot_gap'],
            sync_s3_pkl=variant['sync_pkl'],
        )


def main():
    args = parse_args()
    variant_generator = get_variants(args)
    launch_experiments(variant_generator, args)


if __name__ == '__main__':
    main()
