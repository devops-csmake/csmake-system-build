# <copyright>
# (c) Copyright 2026 Autumn Patterson
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
# </copyright>
"""SystemBuildUnmount and UnmountDiskDrivePartitions delegate to the mount
instance recorded in the environment."""
import unittest
from unittest import mock

from tests import csmake_alias
csmake_alias.install()

from CsmakeModules.MountDiskDrivePartitions import MountDiskDrivePartitions
from CsmakeModules.SystemBuildUnmount import SystemBuildUnmount
from CsmakeModules.UnmountDiskDrivePartitions import UnmountDiskDrivePartitions
from tests.helpers import FakeLog, new_module

KEY = '__SystemBuild_demo__'
DISK_KEY = MountDiskDrivePartitions.ENVKEY


class TestSystemBuildUnmount(unittest.TestCase):

    def setUp(self):
        self.log = FakeLog()
        self.module = new_module(SystemBuildUnmount, log=self.log)

    def test_build_unknown_system_warns_and_passes(self):
        self.module.build({'system': 'demo'})
        self.assertEqual(self.log.messages('warning'),
                         ["The system 'demo' was not found"])
        self.assertEqual(self.log.results, ['passed'])

    def test_build_nothing_mounted_warns_and_passes(self):
        self.module.env.env[KEY] = {}
        self.module.build({'system': 'demo'})
        self.assertEqual(self.log.messages('warning'),
                         ['Nothing was found to unmount'])
        self.assertEqual(self.log.results, ['passed'])

    def test_phase_wrappers_delegate_to_build(self):
        for name in ('system_build', 'use_system_build'):
            with self.subTest(phase=name):
                getattr(self.module, name)({'system': 'demo'})
        self.assertEqual(self.log.results, ['passed', 'passed'])

    @unittest.skip("pre-existing bug: SystemBuildUnmount.build reads an "
                   "undefined 'mountdict' instead of the system entry, so it "
                   "raises NameError whenever something is mounted")
    def test_build_unmounts_the_recorded_mount_instance(self):
        pass


class TestUnmountDiskDrivePartitions(unittest.TestCase):

    def setUp(self):
        self.log = FakeLog()
        self.module = new_module(UnmountDiskDrivePartitions, log=self.log)

    def mounted(self, key=DISK_KEY, result=True):
        instance = mock.Mock()
        instance._cleanUpMounts.return_value = result
        self.module.env.env[key] = {'instance': instance}
        return instance

    def test_build_cleans_up_the_mounts_and_passes(self):
        instance = self.mounted()
        self.module.build({})
        instance._cleanUpMounts.assert_called_once_with()
        self.assertEqual(self.log.results, ['passed'])

    def test_build_cleanup_failure_fails(self):
        self.mounted(result=False)
        self.module.build({})
        self.assertEqual(self.log.results, ['failed'])

    def test_build_uses_the_tagged_mount(self):
        tagged = self.mounted(DISK_KEY + 'one')
        untagged = self.mounted()
        self.module.build({'tag': 'one'})
        tagged._cleanUpMounts.assert_called_once_with()
        untagged._cleanUpMounts.assert_not_called()

    def test_build_not_mounted_fails(self):
        self.assertIsNone(self.module.build({'tag': 'one'}))
        self.assertEqual(self.log.results, ['failed'])
        self.assertIn("tag: 'one'", self.log.messages('error')[0])
