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
"""SystemBuildPopulateFstab writes the fstab (real file I/O in a temp dir:
the content is the subject) and installs it with sudo mv/chown/chmod, which
are mocked at the subprocess boundary."""
import os
import shutil
import subprocess
import tempfile
import types

from tests import csmake_alias
csmake_alias.install()

from CsmakeModules.SystemBuildPopulateFstab import SystemBuildPopulateFstab
from tests.helpers import SAMPLE_FILESYSTEM, SubprocessTestCase, new_module

KEY = '__SystemBuild_demo__'
OPTS = "noatime,errors=remount-ro"


class TestPopulateFstab(SubprocessTestCase):

    def setUp(self):
        SubprocessTestCase.setUp(self)
        self.results = tempfile.mkdtemp(prefix='fstabtest')
        self.addCleanup(shutil.rmtree, self.results, True)
        self.fstab = '/build/mnt/etc/fstab'
        self.temp = os.path.join(self.results, 'temp_etc_fstab')
        self.system = {
            'filesystem': dict(SAMPLE_FILESYSTEM),
            'mountInstance': types.SimpleNamespace(
                _systemMountLocation=lambda: '/build/mnt'),
            'disks': {'sda': {'swaps': [('swap0', {'fstab-id': 'LABEL=swap0'})]},
                      'sdb': {}},
        }
        self.module = new_module(
            SystemBuildPopulateFstab, log=self.log,
            env={KEY: self.system, 'RESULTS': self.results})

    def read(self):
        with open(self.temp) as handle:
            return handle.read()

    def test_build_writes_lines_in_mountpoint_order_with_swap_last(self):
        lines = self.module.build({'system': 'demo'})
        self.assertEqual(lines, [
            "LABEL=root\t/\text4\t%s\t0\t1\n" % OPTS,
            "LABEL=boot\t/boot\text2\t%s\t0\t1\n" % OPTS,
            "LABEL=efi\t/boot/efi\tvfat\t%s\t0\t1\n" % OPTS,
            "LABEL=home\t/home\text4\t%s\t0\t1\n" % OPTS,
            "LABEL=swap0\tswap\tswap\tdefaults\t0\t0\n"])
        self.assertEqual(self.read(), ''.join(lines))
        self.assertEqual(self.log.results, ['passed'])

    def test_build_installs_the_file_with_mv_chown_chmod_in_order(self):
        self.module.build({'system': 'demo'})
        self.assertEqual(self.sp.all_cmds(), [
            ['mv', self.temp, self.fstab],
            ['chown', '0:0', self.fstab],
            ['chmod', '644', self.fstab]])
        self.assertTrue(all(call.sudo for call in self.sp.calls))

    def test_build_without_swap_writes_only_filesystems(self):
        self.system['disks'] = {'sda': {}}
        lines = self.module.build({'system': 'demo'})
        self.assertEqual(len(lines), 4)

    def test_build_non_ascii_device_id_is_written(self):
        self.system['filesystem'] = {
            '/': ('/', '/dev/loop1p1', 'ext4', 'LABEL=róot')}
        self.system['disks'] = {}
        self.module.build({'system': 'demo'})
        with open(self.temp, encoding='utf-8') as handle:
            self.assertIn('LABEL=róot', handle.read())

    def test_build_mv_failure_propagates_before_chown(self):
        self.sp.on('mv', rc=1)
        with self.assertRaises(subprocess.CalledProcessError):
            self.module.build({'system': 'demo'})
        self.assertEqual(self.sp.cmds('chown'), [])

    def test_build_chmod_failure_propagates(self):
        self.sp.on('chmod', rc=1)
        with self.assertRaises(subprocess.CalledProcessError):
            self.module.build({'system': 'demo'})

    def test_build_undefined_system_fails(self):
        self.module.env.env.pop(KEY)
        self.assertIsNone(self.module.build({'system': 'demo'}))
        self.assertEqual(self.log.results, ['failed'])

    def test_build_system_without_filesystem_fails(self):
        del self.system['filesystem']
        self.assertIsNone(self.module.build({'system': 'demo'}))
        self.assertEqual(self.log.results, ['failed'])

    def test_build_unmounted_system_fails(self):
        del self.system['mountInstance']
        self.assertIsNone(self.module.build({'system': 'demo'}))
        self.assertEqual(self.log.results, ['failed'])
        self.assertEqual(self.sp.calls, [])

    def test_system_build_delegates_to_build(self):
        self.assertEqual(len(self.module.system_build({'system': 'demo'})), 5)
