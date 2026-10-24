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
"""Mount order matters (parents before children) and the fstab is written in
the same order.  Both used dict.keys().sort(), which is an AttributeError on
a Python 3 dict view.  sudo is a fake that records instead of mounting."""
import os
import types

from tests import csmake_alias
csmake_alias.install()

from CsmakeModules.SystemBuildMount import SystemBuildMount
from CsmakeModules.SystemBuildPopulateFstab import SystemBuildPopulateFstab
from tests.helpers import FakeBinTestCase, SAMPLE_FILESYSTEM as FILESYSTEM


class TestSystemBuildMountOrder(FakeBinTestCase):

    def test_mount_mounts_parents_before_children(self):
        module = object.__new__(SystemBuildMount)
        module.log = self.log
        module.options = {'location': os.path.join(self.tmp, 'mnt')}
        os.mkdir(module.options['location'])
        module.fsEntry = dict(FILESYSTEM)
        module.skipmounts = ['/home']
        module.mountedDevices = []
        module.systemEntry = {'cleanup_methods': []}

        self.assertTrue(module._mount())

        mounted = [call[1:] for call in self.bin.calls('mount')
                   if not call[1].startswith('-')]
        location = module.options['location']
        self.assertEqual(mounted, [
            ['/dev/loop3p3', location + '/'],                          # /
            ['/dev/loop3p2', os.path.join(location, 'boot')],          # /boot
            ['/dev/loop3p1', os.path.join(location, 'boot', 'efi')],   # /boot/efi
        ])
        self.assertEqual(module.log.messages('debug'),
                         ['Skipping mount: /home'])
        # The real filesystems are tracked first, in that same order
        self.assertEqual(module.mountedDevices[:3], [
            location + '/',
            os.path.join(location, 'boot'),
            os.path.join(location, 'boot', 'efi')])
        self.assertEqual(module.systemEntry['cleanup_methods'], [module._onExit])


class TestSystemBuildPopulateFstab(FakeBinTestCase):

    def test_fstab_lines_are_written_in_mountpoint_order(self):
        mountDir = os.path.join(self.tmp, 'mnt')
        os.makedirs(os.path.join(mountDir, 'etc'))
        resultsDir = os.path.join(self.tmp, 'results')
        os.mkdir(resultsDir)
        # sudo mv is the real mv here: it only touches the temp dirs above
        self.bin.add('mv', extra='/bin/mv "$@"')

        mountInstance = types.SimpleNamespace(
            _systemMountLocation=lambda: mountDir)
        swap = {'fstab-id': 'LABEL=swap0'}
        system = {
            'filesystem': dict(FILESYSTEM),
            'mountInstance': mountInstance,
            'disks': {'sda': {'swaps': [('swap0', swap)]}, 'sdb': {}},
        }
        module = object.__new__(SystemBuildPopulateFstab)
        module.log = self.log
        module.env = types.SimpleNamespace(env={
            '__SystemBuild_demo__': system, 'RESULTS': resultsDir})

        lines = module.build({'system': 'demo'})

        opts = "noatime,errors=remount-ro"
        self.assertEqual(lines, [
            "LABEL=root\t/\text4\t%s\t0\t1\n" % opts,
            "LABEL=boot\t/boot\text2\t%s\t0\t1\n" % opts,
            "LABEL=efi\t/boot/efi\tvfat\t%s\t0\t1\n" % opts,
            "LABEL=home\t/home\text4\t%s\t0\t1\n" % opts,
            "LABEL=swap0\tswap\tswap\tdefaults\t0\t0\n",
        ])
        with open(os.path.join(mountDir, 'etc', 'fstab')) as fstab:
            self.assertEqual(fstab.read(), ''.join(lines))
        fstabPath = os.path.join(mountDir, 'etc', 'fstab')
        self.assertEqual(self.bin.calls('chown'), [['chown', '0:0', fstabPath]])
        self.assertEqual(self.bin.calls('chmod'), [['chmod', '644', fstabPath]])
