import os
# import csv
import numpy as np
from PIL import Image
import torch
from torch.autograd import Variable
import matplotlib.pyplot as plt

from motion_planning.perception_policy import Predictor, end_effector_pose
from behavioural_vae.ros_monitor import ROSTrajectoryVAE
from gibson.ros_monitor import RosPerceptionVAE

from motion_planning.utils import parse_arguments, GIBSON_ROOT, load_parameters, BEHAVIOUR_ROOT, POLICY_ROOT, use_cuda
from motion_planning.utils import LOOK_AT, DISTANCE, AZIMUTH, ELEVATION, LOOK_AT_EPSILON, CUP_NAMES, KINECT_EXPERIMENTS_PATH
from motion_planning.utils import ELEVATION_EPSILON, AZIMUTH_EPSILON, DISTANCE_EPSILON
from behavioural_vae.utils import MIN_ANGLE, MAX_ANGLE
import pandas as pd

#    print("Give the position of a cup:")
#    x = float(raw_input("Enter x: "))
#    y = float(raw_input("Enter y: "))
#    ('camera_pose', [0.729703198019277, 0.9904542035333381, 0.5861775350680969])
#    ('Kinect lookat', array([0.71616937, -0.03126261, 0.]))
#    ('distance', 1.1780036104266332)
#    ('azimuth', -90.75890510585465)
#    ('kinect_elevation', -29.841508670508976)

# OLD Camera params (these values were used when training old policy)

# LOOK_AT = [0.70, 0.0, 0.0]
# DISTANCE = 1.2
# AZIMUTH = -90.
# ELEVATION = -30
# ELEVATION_EPSILON = 0.5
# AZIMUTH_EPSILON = 0.5
# DISTANCE_EPSILON = 0.05

# Camera values when samples were gathered

# KINECT_LOOKAT = [0.71616937, -0.03126261, 0.]
# KINECT_DISTANCE = 1.1780036104266332
# KINECT_AZIMUTH = -90.75890510585465
# KINECT_ELEVATION = -29.841508670508976


def take_num(elem):
    elem = elem.split('_')[-1]
    elem = elem.split('.')[0]
    val = int(elem)
    return val

def main(args):

    device = use_cuda()

    assert(args.model_index > -1)

    bahavior_model_path = os.path.join(BEHAVIOUR_ROOT, args.vae_name)
    action_vae = ROSTrajectoryVAE(bahavior_model_path, args.latent_dim, args.num_actions,
                                  model_index=args.model_index, num_joints=args.num_joints)

    # Trajectory generator
    traj_decoder = action_vae.model.decoder

    gibson_model_path = os.path.join(GIBSON_ROOT, args.g_name)
    perception = RosPerceptionVAE(gibson_model_path, args.g_latent)

    # Policy
    policy = Predictor(args.g_latent + 5, args.latent_dim, args.num_params)
    policy.to(device)
    policy_path = os.path.join(POLICY_ROOT, args.policy_name)
    load_parameters(policy, policy_path, 'model')

    # Kinect data
    log_path = os.path.join(KINECT_EXPERIMENTS_PATH, args.log_name)

    # Getting object poses
    data = pd.read_csv(os.path.join(log_path, 'cup_log.csv'))
    data = data.values
    cup_poses = np.array(data[:, 1:3], dtype=np.float32)
    end_effector_poses = np.array(data[:, 3:5], dtype=np.float32)
    kinect_lookats = np.array(data[:, 5:7], dtype=np.float32)
    kinect_distances = np.array(data[:, 7])
    kinect_azimuths = np.array(data[:, 8])
    kinect_elevations = np.array(data[:, 9])

    # Camera param normalization
    n_lookat_xs = (kinect_lookats[:, 0] - (np.array(LOOK_AT[0]) - LOOK_AT_EPSILON)) / (LOOK_AT_EPSILON * 2)
    n_lookat_ys = (kinect_lookats[:, 1] - (np.array(LOOK_AT[1]) - LOOK_AT_EPSILON)) / (LOOK_AT_EPSILON * 2)
    n_camera_distances = (kinect_distances - (DISTANCE - DISTANCE_EPSILON)) / (DISTANCE_EPSILON * 2)
    n_azimuths = (kinect_azimuths - (AZIMUTH - AZIMUTH_EPSILON)) / (AZIMUTH_EPSILON * 2)
    n_elevations = (kinect_elevations - (ELEVATION - ELEVATION_EPSILON)) / (ELEVATION_EPSILON * 2)

    camera_params = np.array([n_lookat_xs, n_lookat_ys, n_camera_distances, n_azimuths, n_elevations], np.float)

    debug_images = np.array(data[:, 13], str)

    end_poses = []
    distances = []
    sim_real_errors = []

    for i in range(camera_params.shape[1]):

        image_path = os.path.join(os.path.join(log_path, "inputs"), debug_images[i])

        image = Image.open(image_path)

        width, height = image.size
        left = 0
        top = args.top_crop
        right = width - args.width_crop
        bottom = height
        image = image.crop((left, top, right, bottom))

        # Image -> Latent1
        latent1 = perception.get_latent(image)

        camera_input = Variable(torch.Tensor(camera_params[:, i]).to(device))
        camera_input = camera_input.unsqueeze(0)
        latent1 = torch.cat([latent1, camera_input], 1)

        # latent and camera params -> latent2
        latent2 = policy(latent1)
        trajectories = traj_decoder(latent2)

        # Reshape to trajectories
        trajectories = action_vae.model.to_trajectory(trajectories)

        end_joint_pose = trajectories[:, :, -1]

        end_joint_pose = (MAX_ANGLE - MIN_ANGLE) * end_joint_pose + MIN_ANGLE
        # joint pose -> cartesian
        end_pose = end_effector_pose(end_joint_pose, device)
        end_pose = end_pose.cpu().detach().numpy()[0]

        end_poses.append(end_pose)
        distance = np.linalg.norm(end_pose - cup_poses[i])
        distances.append(distance)
        sim_real_error = np.linalg.norm(end_pose - end_effector_poses[i])
        sim_real_errors.append(sim_real_error)

    end_poses = np.array(end_poses)

    save_path = os.path.join(log_path, args.policy_name)
    if not(os.path.exists(save_path)):
        os.makedirs(save_path)

    f = open(os.path.join(save_path, 'avg_errors_t_{}_w_{}_crops.txt'.format(args.top_crop, args.width_crop)), 'w')
    f.write("avg goal distance {}\n".format(np.mean(distances)))

    print("avg goal distance", np.mean(distances))

    if args.real_hw:
        print("avg real sim distance", np.mean(sim_real_errors))
        f.write("avg real sim distance {}\n".format(np.mean(sim_real_errors)))

    fig, axes = plt.subplots(3, 3, sharex=True, figsize=[30, 30])

    cup_names = np.unique(np.array(data[:, 0], str))

    for i, cup_name in enumerate(cup_names):

        ax = axes[int(i/3)][i%3]
        cup_indices = np.array([cup_name in s for s in data[:, 0]])

        goal_poses = cup_poses[cup_indices]
        pred_poses = end_poses[cup_indices]

        print(cup_name, 'avg goal error:', np.linalg.norm(goal_poses - pred_poses, axis=1).mean())
        f.write("{} avg goal error {}\n".format(cup_name, np.linalg.norm(goal_poses - pred_poses, axis=1).mean()))

        ax.scatter(goal_poses[:, 0], goal_poses[:, 1], c='r', label='real')
        ax.scatter(pred_poses[:, 0], pred_poses[:, 1], c='b', label='pred')

        if args.real_hw:
            hw_poses = end_effector_poses[cup_indices]
            print(cup_name, 'avg hw real error:', np.linalg.norm(hw_poses - pred_poses, axis=1).mean())
            f.write("{} avg hw real error {}\n".format(cup_name, np.linalg.norm(hw_poses - pred_poses, axis=1).mean()))
            ax.scatter(hw_poses[:, 0], hw_poses[:, 1], c='g', label='hw')

        ax.set_title(cup_name)
        ax.set_xlabel('x')
        ax.set_ylabel('y')
        ax.legend()

    plt.savefig(os.path.join(save_path, 'simulation_result_t_{}_w_{}_crops.png'.format(args.top_crop, args.width_crop)))

    if args.real_hw:
        np.save(os.path.join(save_path, 'results.npy'), (cup_poses, end_poses, hw_poses))
    else:
        np.save(os.path.join(save_path, 'results.npy'), (cup_poses, end_poses))




if __name__ == '__main__':
    args = parse_arguments(behavioural_vae=True, gibson=True, policy=True, policy_eval=True, kinect=True)
    main(args)