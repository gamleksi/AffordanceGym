import torch
import numpy as np
from motion_planning.utils import LUMI_X_LIM, LUMI_Y_LIM, LUMI_Z_LIM


class SimpleEnvironment(object):

    def __init__(self, trajectory_model, random_goal, device):
        self.trajectory_model = trajectory_model
        self.random_goal = random_goal
        self.device = device

    def get_state(self):

        if self.random_goal:
            x = np.random.uniform(LUMI_X_LIM[0], LUMI_X_LIM[1])
            y = np.random.uniform(LUMI_Y_LIM[0], LUMI_Y_LIM[1])
            z = np.random.uniform(LUMI_Z_LIM[0], LUMI_Z_LIM[1])
        else:
            x = (LUMI_X_LIM[0] + LUMI_X_LIM[1]) / 2.
            y = (LUMI_Y_LIM[0] + LUMI_Y_LIM[1]) / 2.
            z = (LUMI_Z_LIM[0] + LUMI_Z_LIM[1]) / 2.

        return np.array([x, y, z]), np.array([x, y, z])

    def get_reward(self, goal, end_pose):
        norm_denumerator = [1. / (LUMI_X_LIM[1] - LUMI_X_LIM[0]), 1. / (LUMI_Y_LIM[1] - LUMI_Y_LIM[0]), 1.]
        norm_denumerator = torch.tensor(norm_denumerator).to(self.device)
        norm_diff = (goal - end_pose) * norm_denumerator
        reward = -np.linalg.norm(norm_diff)
        return reward

    def do_action(self, action):
        _, achieved_pose = self.trajectory_model.do_latent_imitation(
            action)
        end_pose = np.array((
            achieved_pose.pose.position.x,
            achieved_pose.pose.position.y,
            achieved_pose.pose.position.z))
        return end_pose

    def reset(self):
        self.trajectory_model.reset_environment()