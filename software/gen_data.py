"""
Scripts for generating train data.
"""

import time
from pathlib import Path

import cv2
import numpy as np

from camera import *


class DataGen:
    def __init__(self, dir):
        self.dir = dir
        self.i = 0
        for file in dir.iterdir():
            if file.is_file and file.stem.isdigit():
                self.i = max(self.i, int(file.stem) + 1)

    def write(self, images, label):
        x = images_to_tensor(images)
        torch.save(x, self.dir / f"{self.i}.pt")

        with open(self.dir / f"{self.i}.txt", "w") as f:
            f.write(f"{label}\n")

        print("Write", self.i)
        self.i += 1


def manual_rc(args, interface, wrapper, data_gen):
    while True:
        images = wrapper.get()

        if interface.rc_values[5] > 0.5:
            label = interface.rc_values[0] * 2 - 1
            data_gen.write(images, label)

        time.sleep(args.interval)


def self_rc(args, interface, wrapper, data_gen):
    # Mask for depth_x.
    mask = np.zeros((args.res, args.res), dtype=np.float32)
    for y in range(args.res):
        value = 1 - abs(y - args.res / 2) / (args.res / 2)
        mask[y] = value

    # EMA smoothed depth.
    ema_fac = 0.3
    depth_ema = np.zeros((args.res,), dtype=np.float32)

    while True:
        interface.ena = interface.rc_values[4] > 0.5

        images = wrapper.get()

        # Process depth to obtain depth over X.
        depth = images["depth_fac"]
        depth = cv2.GaussianBlur(depth, (5, 5), 0)
        depth = depth * mask
        depth_x = np.max(depth, axis=0)
        depth_x = np.clip(depth_x / 60, 0, 1)
        depth_ema = depth_ema * (1 - ema_fac) + depth_x * ema_fac

        """
        img = np.zeros((args.res, args.res), dtype=np.uint8)
        for i in range(args.res):
            img[i] = depth_ema * 255
        cv2.imshow("depth", img)
        cv2.waitKey(1)
        """

        # Figure out resulting action.
        left_fac = np.max(depth_ema[: args.res // 2])
        right_fac = np.max(depth_ema[args.res // 2 :])

        if left_fac > 0.8 and right_fac > 0.8:
            # Back out
            interface.v1 = interface.v2 = 0
            time.sleep(0.5)
            interface.v1 = interface.v2 = -1
            time.sleep(0.5)
            if left_fac > right_fac:
                interface.v1 = 0
            else:
                interface.v2 = 0
            time.sleep(0.7)
            interface.v1 = interface.v2 = 0
            time.sleep(0.5)

        elif left_fac > 0.3 or right_fac > 0.3:
            steer = (left_fac - right_fac) * 3
            steer = min(1, abs(steer))
            interface.v1 = 1
            interface.v2 = 1
            if left_fac < right_fac:
                interface.v1 = 1 - steer
            else:
                interface.v2 = 1 - steer

        else:
            interface.v1 = 1
            interface.v2 = 1

        time.sleep(0.01)


def gen_data_main(args, interface):
    dir = Path(args.dir)
    dir.mkdir(exist_ok=True, parents=True)
    data_gen = DataGen(dir)

    pipeline = create_pipeline(args.res)
    print("Setup Depthai pipeline.")

    with depthai.Device(pipeline) as device:
        wrapper = PipelineWrapper(device)

        if args.self_rc:
            self_rc(args, interface, wrapper, data_gen)
        else:
            interface.add_thread(interface.auto_rc)
            manual_rc(args, interface, wrapper, data_gen)
