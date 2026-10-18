"""Hardware-free transport and motion-lock regression tests.

Run from the project directory with::

    python -m unittest discover -s tests -v

Every hardware connection below uses a fake SDK; these tests never access CAN
devices and do not establish that a physical arm or Windows driver works.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch, sentinel

from piper_x_controller import PiperXController
from piper_x_platform import (
    default_pose_file,
    resolve_can_connection,
    user_config_directory,
)


class PlatformSelectionTests(unittest.TestCase):
    def test_defaults_match_the_platform(self) -> None:
        cases = (
            ("Windows", "agx_cando", "0"),
            ("Linux", "socketcan", "can0"),
        )
        for system, interface, channel in cases:
            with self.subTest(system=system):
                with patch("piper_x_platform.platform.system", return_value=system):
                    self.assertEqual(
                        resolve_can_connection(), (interface, channel)
                    )
                    controller = PiperXController(
                        can_port=None, can_interface="auto", dry_run=False
                    )
                self.assertEqual(controller.can_interface, interface)
                self.assertEqual(controller.can_port, channel)
                self.assertIsInstance(controller.can_port, str)
                self.assertFalse(controller.connected)
                self.assertFalse(controller.motion_armed)

    def test_explicit_channels_are_preserved(self) -> None:
        cases = (
            ("Windows", "auto", "agx_cando", "2"),
            ("Windows", "agx_cando", "agx_cando", "2"),
            ("Linux", "auto", "socketcan", "can_piper"),
            ("Linux", "socketcan", "socketcan", "can_piper"),
        )
        for system, requested, expected, channel in cases:
            with self.subTest(system=system, interface=requested, channel=channel):
                self.assertEqual(
                    resolve_can_connection(
                        can_port=channel, can_interface=requested, system=system
                    ),
                    (expected, channel),
                )
                with patch("piper_x_platform.platform.system", return_value=system):
                    controller = PiperXController(
                        can_port=channel, can_interface=requested
                    )
                self.assertEqual(controller.can_interface, expected)
                self.assertEqual(controller.can_port, channel)

    def test_windows_rejects_a_socketcan_name_before_loading_sdk(self) -> None:
        for interface in ("auto", "agx_cando"):
            with self.subTest(interface=interface):
                with patch("piper_x_platform.platform.system", return_value="Windows"):
                    with patch.object(PiperXController, "_load_sdk") as load_sdk:
                        with self.assertRaises(ValueError):
                            PiperXController(
                                can_port="can0", can_interface=interface
                            )
                        load_sdk.assert_not_called()

    def test_unknown_backend_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resolve_can_connection(can_interface="not_a_backend", system="Windows")

    def test_windows_demo_and_real_waypoints_use_distinct_user_files(self) -> None:
        # Importing this module must not create a Tk window or need a display.
        from piper_x_remote import default_task_file

        with tempfile.TemporaryDirectory() as directory:
            local_app_data = Path(directory) / "User With Spaces" / "Local"
            with patch.dict(os.environ, {"LOCALAPPDATA": str(local_app_data)}):
                with patch("piper_x_platform.platform.system", return_value="Windows"):
                    expected_directory = local_app_data / "NXTektal" / "PiPER-X"
                    self.assertEqual(user_config_directory(), expected_directory)
                    files = (
                        default_task_file(dry_run=False),
                        default_task_file(dry_run=True),
                        default_pose_file(dry_run=False),
                        default_pose_file(dry_run=True),
                    )
            self.assertEqual(
                files,
                tuple(
                    expected_directory / name
                    for name in (
                        "basket_task.json",
                        "basket_task_demo.json",
                        "poses.json",
                        "poses_demo.json",
                    )
                ),
            )
            self.assertEqual(len(set(files)), 4)


def make_fake_sdk():
    """Build two separate arms to expose mistakes in the firmware reconnect."""
    firmware = {"software_version": "test-version", "hardware_version": "test-arm"}
    probe = Mock(name="firmware_probe")
    probe.get_firmware.return_value = firmware

    arm = Mock(name="controller_arm")
    arm.OPTIONS = SimpleNamespace(
        EFFECTOR=SimpleNamespace(AGX_GRIPPER=sentinel.agx_gripper),
        INSTALLATION_POS=SimpleNamespace(HORIZONTAL=sentinel.horizontal),
    )
    arm.get_joint_angles.return_value = SimpleNamespace(msg=[0.0] * 6)
    arm.get_arm_status.return_value = SimpleNamespace(
        msg=SimpleNamespace(arm_status=0, motion_status=0)
    )
    # Even an arm already enabled by another client must stay behind the local
    # explicit-enable lock when this controller first connects.
    arm.get_joints_enable_status_list.return_value = [True] * 6
    arm.enable.return_value = True

    create_cfg = Mock(name="create_agx_arm_config", side_effect=lambda **kw: dict(kw))
    factory = SimpleNamespace(create_arm=Mock(side_effect=[probe, arm]))
    resolve_profile = Mock(return_value=sentinel.firmware_profile)
    sdk = {
        "AgxArmFactory": factory,
        "ArmModel": SimpleNamespace(PIPER_X=sentinel.piper_x),
        "create_agx_arm_config": create_cfg,
        "resolve_firmware_profile": resolve_profile,
    }
    return sdk, firmware, probe, arm


class HardwareConnectionTests(unittest.TestCase):
    def test_transport_is_forwarded_in_both_connection_phases_without_motion(self) -> None:
        cases = (
            ("Windows", None, "agx_cando", "0"),
            ("Windows", "2", "agx_cando", "2"),
            ("Linux", None, "socketcan", "can0"),
            ("Linux", "can_piper", "socketcan", "can_piper"),
        )
        for system, requested_channel, interface, channel in cases:
            with self.subTest(system=system, channel=channel):
                sdk, firmware, probe, arm = make_fake_sdk()
                with patch("piper_x_platform.platform.system", return_value=system):
                    with patch.object(PiperXController, "_load_sdk", return_value=sdk):
                        controller = PiperXController(
                            can_port=requested_channel, can_interface="auto"
                        )
                        self.assertEqual(controller.connect(), firmware)

                self.addCleanup(controller.disconnect)
                self.assertTrue(controller.connected)
                self.assertFalse(controller.motion_armed)
                probe.connect.assert_called_once_with()
                probe.disconnect.assert_called_once_with()
                arm.connect.assert_called_once_with()

                config_calls = sdk["create_agx_arm_config"].call_args_list
                self.assertEqual(len(config_calls), 2)
                for config_call in config_calls:
                    self.assertEqual(config_call.kwargs["robot"], sentinel.piper_x)
                    self.assertEqual(config_call.kwargs["interface"], interface)
                    self.assertEqual(config_call.kwargs["channel"], channel)
                    self.assertIsInstance(config_call.kwargs["channel"], str)
                    self.assertEqual(config_call.kwargs["bitrate"], 1_000_000)
                self.assertNotIn("firmeware_version", config_calls[0].kwargs)
                self.assertEqual(
                    config_calls[1].kwargs["firmeware_version"],
                    sentinel.firmware_profile,
                )
                sdk["resolve_firmware_profile"].assert_called_once_with(
                    sentinel.piper_x, firmware["software_version"]
                )
                sdk["AgxArmFactory"].create_arm.assert_any_call(
                    dict(config_calls[0].kwargs)
                )
                sdk["AgxArmFactory"].create_arm.assert_any_call(
                    dict(config_calls[1].kwargs)
                )

                for command in (
                    lambda: controller.move_joints_deg([1.0] * 6),
                    lambda: controller.move_pose_deg([0.25, 0, 0.25, 0, 90, 0]),
                    lambda: controller.move_gripper_mm(10.0),
                ):
                    with self.assertRaisesRegex(RuntimeError, "[Ll]ocked"):
                        command()

                for robot in (probe, arm):
                    for method in (
                        "enable", "disable", "move_j", "move_p", "move_l",
                        "set_installation_pos", "set_speed_percent",
                    ):
                        getattr(robot, method).assert_not_called()
                arm.init_effector.return_value.move_gripper_m.assert_not_called()

    def test_explicit_enable_applies_configuration_before_enabling_the_arm(self) -> None:
        sdk, _firmware, _probe, arm = make_fake_sdk()
        with patch("piper_x_platform.platform.system", return_value="Windows"):
            with patch.object(PiperXController, "_load_sdk", return_value=sdk):
                controller = PiperXController(speed_percent=11)
                controller.connect()
        self.addCleanup(controller.disconnect)
        arm.set_installation_pos.assert_not_called()
        arm.set_speed_percent.assert_not_called()
        arm.enable.assert_not_called()
        self.assertTrue(controller.enable())
        self.assertTrue(controller.motion_armed)
        arm.assert_has_calls(
            [
                call.set_installation_pos(sentinel.horizontal),
                call.set_speed_percent(11),
                call.enable(),
            ],
            any_order=False,
        )

    def test_failed_control_connection_releases_handle_and_clears_state(self) -> None:
        cases = (
            ("connect", False),
            ("init_effector", False),
            ("init_effector", True),
        )
        for failure_stage, cleanup_fails in cases:
            with self.subTest(stage=failure_stage, cleanup_fails=cleanup_fails):
                sdk, _firmware, probe, arm = make_fake_sdk()
                failure_message = f"simulated {failure_stage} failure"
                getattr(arm, failure_stage).side_effect = RuntimeError(failure_message)
                if cleanup_fails:
                    arm.disconnect.side_effect = RuntimeError("simulated cleanup failure")
                with patch("piper_x_platform.platform.system", return_value="Windows"):
                    with patch.object(PiperXController, "_load_sdk", return_value=sdk):
                        controller = PiperXController()
                        with self.assertRaisesRegex(RuntimeError, failure_message):
                            controller.connect()
                probe.disconnect.assert_called_once_with()
                arm.disconnect.assert_called_once_with()
                self.assertIsNone(controller.robot)
                self.assertIsNone(controller.gripper)
                self.assertFalse(controller.connected)
                self.assertFalse(controller.motion_armed)
                arm.enable.assert_not_called()
                controller.disconnect()
                arm.disconnect.assert_called_once_with()

    def test_probe_error_disconnects_without_enabling_or_creating_control_arm(self) -> None:
        sdk, _firmware, probe, arm = make_fake_sdk()
        probe.get_firmware.side_effect = RuntimeError("simulated CAN read failure")
        with patch("piper_x_platform.platform.system", return_value="Windows"):
            with patch.object(PiperXController, "_load_sdk", return_value=sdk):
                controller = PiperXController()
                with self.assertRaisesRegex(RuntimeError, "simulated CAN read failure"):
                    controller.connect()
        self.assertFalse(controller.connected)
        self.assertFalse(controller.motion_armed)
        probe.disconnect.assert_called_once_with()
        probe.enable.assert_not_called()
        arm.connect.assert_not_called()
        self.assertEqual(sdk["AgxArmFactory"].create_arm.call_count, 1)


class DryRunSafetyTests(unittest.TestCase):
    def test_simulation_never_loads_sdk_and_requires_enable_after_stop_or_reconnect(self) -> None:
        for system in ("Windows", "Linux"):
            with self.subTest(system=system):
                with patch("piper_x_platform.platform.system", return_value=system):
                    with patch.object(
                        PiperXController,
                        "_load_sdk",
                        side_effect=AssertionError("Dry-run must not load the SDK"),
                    ) as load_sdk:
                        controller = PiperXController(dry_run=True)
                        self.assertFalse(controller.motion_armed)
                        with self.assertRaises(RuntimeError):
                            controller.enable()

                        firmware = controller.connect()
                        self.assertEqual(firmware["software_version"], "DRY-RUN")
                        self.assertTrue(controller.get_snapshot().communication_ok)
                        self.assertFalse(controller.motion_armed)
                        self.assert_all_motion_locked(controller)

                        self.assertTrue(controller.enable())
                        controller.move_joints_deg([1, 2, 3, 4, 5, 6])
                        controller.move_pose_deg([0.3, 0.1, 0.2, 0, 90, 0])
                        controller.move_gripper_mm(12, force_n=1.5)
                        snapshot = controller.get_snapshot()
                        for actual, expected in zip(snapshot.joint_deg, range(1, 7)):
                            self.assertAlmostEqual(actual, expected)
                        self.assertEqual(snapshot.flange_pose[:3], [0.3, 0.1, 0.2])
                        self.assertEqual(snapshot.gripper_width_mm, 12.0)

                        controller.emergency_stop()
                        self.assertFalse(controller.motion_armed)
                        self.assert_all_motion_locked(controller)
                        controller.reset()
                        self.assertFalse(controller.motion_armed)
                        self.assert_all_motion_locked(controller)

                        self.assertTrue(controller.enable())
                        controller.move_joints_deg([0] * 6)
                        controller.disconnect()
                        self.assertFalse(controller.connected)
                        self.assertFalse(controller.motion_armed)
                        controller.connect()
                        self.assertFalse(controller.motion_armed)
                        self.assert_all_motion_locked(controller)
                        controller.disconnect()
                        load_sdk.assert_not_called()

    def assert_all_motion_locked(self, controller: PiperXController) -> None:
        commands = (
            lambda: controller.move_joints_deg([0] * 6),
            lambda: controller.move_pose_deg([0.25, 0, 0.25, 0, 90, 0]),
            lambda: controller.move_pose_deg([0.25, 0, 0.25, 0, 90, 0], linear=True),
            lambda: controller.move_gripper_mm(10),
        )
        for command in commands:
            with self.assertRaisesRegex(RuntimeError, "[Ll]ocked"):
                command()


if __name__ == "__main__":
    unittest.main()
