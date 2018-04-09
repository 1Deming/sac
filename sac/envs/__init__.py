from .gym_env import GymEnv
from .multi_direction_env import (
    MultiDirectionSwimmerEnv,
    MultiDirectionAntEnv,
    MultiDirectionHumanoidEnv)
from .random_goal_swimmer_env import RandomGoalSwimmerEnv
from .random_goal_ant_env import RandomGoalAntEnv
from .random_goal_humanoid_env import RandomGoalHumanoidEnv
from .random_wall_ant_env import RandomWallAntEnv

from .cross_maze_ant_env import CrossMazeAntEnv
from .simple_maze_ant_env import SimpleMazeAntEnv

from .hierarchy_proxy_env import HierarchyProxyEnv
from .multigoal import MultiGoalEnv
