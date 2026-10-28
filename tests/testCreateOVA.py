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
"""CreateOVA builds a tar (the OVA) from an in-memory OVF and manifest plus
the disk files.  In Python 3 tarfile needs bytes streams, so run a real
build() and read the resulting tar back."""
import hashlib
import os
import re
import shutil
import tarfile
import tempfile
import unittest

from tests import csmake_alias
csmake_alias.install()

from CsmakeModules.CreateOVA import CreateOVA
from tests.helpers import FakeLog, FakeMapping

DISK_BYTES = bytes(range(256)) * 40 + b'\0\xff\x80 binary tail'


class FakeMetadata:
    def _getMetadataDefinitions(self):
        return {'manufacturer': 'Example Corp'}

    def _getDefaultDefinedVersion(self):
        return '1.2.3'


class OvaTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='ovatest')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.disk = os.path.join(self.tmp, 'root.vmdk')
        with open(self.disk, 'wb') as disk:
            disk.write(DISK_BYTES)
        self.ova = os.path.join(self.tmp, 'appliance.ova')
        self.module = object.__new__(CreateOVA)
        self.module.log = FakeLog()
        self.module.metadata = FakeMetadata()
        self.module.mapping = FakeMapping([(
            [{'location': self.disk, 'intent': 'appliance'}],
            [{'location': self.ova}])])
        self.options = {
            'vm-name': 'testvm',
            'vm-cpus': '2',
            'vm-memory': '2048',
            'os': 'centos64',
            'disk-capacity-appliance': '10G',
            'disk-format-appliance': 'VMDK Stream Optimized',
        }

    def readOva(self):
        with tarfile.open(self.ova) as ova:
            return [(member, ova.extractfile(member).read())
                    for member in ova.getmembers()]


class TestCreateOVA(OvaTestCase):

    def test_build_writes_a_tar_of_ovf_disk_and_manifest_as_bytes(self):
        self.module.build(self.options)
        self.assertEqual(self.module.log.results, ['passed'])
        members = self.readOva()
        # OVF first, disk, then the manifest last (ovf spec ordering)
        self.assertEqual([m.name for m, _ in members],
                         ['appliance.ovf', 'root-disk1.vmdk', 'appliance.mf'])
        contents = dict((m.name, data) for m, data in members)
        self.assertEqual(contents['root-disk1.vmdk'], DISK_BYTES)
        ovf = contents['appliance.ovf'].decode('utf-8')
        self.assertTrue(ovf.startswith('<?xml version="1.0" encoding="UTF-8"?>'))
        self.assertIn('<Name>testvm</Name>', ovf)
        self.assertIn('ovf:href="root-disk1.vmdk"', ovf)
        self.assertIn('ovf:size="%d"' % len(DISK_BYTES), ovf)
        for member, _ in members:
            self.assertEqual(member.size, len(contents[member.name]))
            self.assertEqual(member.mode, 0o644)
            self.assertEqual(member.uname, 'someone')

    def test_manifest_digests_match_the_bytes_in_the_archive(self):
        for fmt, algo, label in [('sha1', hashlib.sha1, 'SHA1'),
                                 ('sha256', hashlib.sha256, 'SHA256')]:
            with self.subTest(manifest_format=fmt):
                if os.path.exists(self.ova):
                    os.remove(self.ova)
                self.options['manifest-format'] = fmt
                self.module.build(self.options)
                contents = dict((m.name, data) for m, data in self.readOva())
                manifest = contents['appliance.mf'].decode('utf-8')
                self.assertTrue(manifest.endswith('\n'))
                entries = dict(
                    re.match(r'%s\((.+)\)= ([0-9a-f]+)$' % label, line).groups()
                    for line in manifest.splitlines())
                self.assertEqual(sorted(entries),
                                 ['appliance.ovf', 'root-disk1.vmdk'])
                for name, digest in entries.items():
                    self.assertEqual(digest, algo(contents[name]).hexdigest())

    def test_unknown_os_lists_the_valid_os_types_and_raises(self):
        self.options['os'] = 'no-such-os'
        with self.assertRaises(KeyError):
            self.module.build(self.options)
        errors = '\n'.join(self.module.log.messages('error'))
        self.assertIn('centos64: CentOS 4/5/6 (64-bit)', errors)
        self.assertEqual(self.module.log.results, ['failed'])


class TestCreateOVAVariants(OvaTestCase):
    """Options, edge cases and failure paths of build()."""

    def test_build_non_ascii_vm_name_is_utf8_and_sized_in_bytes(self):
        self.options['vm-name'] = 'caf\u00e9-\u4e2d\u6587'
        self.module.build(self.options)
        members = dict((m.name, (m, data)) for m, data in self.readOva())
        member, data = members['appliance.ovf']
        self.assertIn('<Name>caf\u00e9-\u4e2d\u6587</Name>', data.decode('utf-8'))
        self.assertEqual(member.size, len(data))
        self.assertGreater(len(data), len(data.decode('utf-8')))
        manifest = members['appliance.mf'][1].decode('utf-8')
        self.assertIn(hashlib.sha1(data).hexdigest(), manifest)

    def test_build_efi_firmware_and_sata_controller_are_written_to_the_ovf(self):
        self.options.update(firmware='EFI', **{'disk-controller': 'sata'})
        self.module.build(self.options)
        ovf = dict((m.name, d) for m, d in self.readOva())['appliance.ovf'].decode()
        self.assertIn('vmw:key="firmware" vmw:value="efi"', ovf)
        self.assertIn('SATA Controller', ovf)
        self.assertNotIn('SCSI Controller', ovf)

    def test_build_cd_dvd_drive_is_optional(self):
        self.options['add-cd-dvd-rom'] = 'True'
        self.module.build(self.options)
        ovf = dict((m.name, d) for m, d in self.readOva())['appliance.ovf'].decode()
        self.assertIn('CD/DVD Drive 1', ovf)

    def test_build_several_disks_are_numbered_and_archived_in_order(self):
        second = os.path.join(self.tmp, 'data.vmdk')
        with open(second, 'wb') as disk:
            disk.write(b'second disk')
        self.module.mapping = FakeMapping(
            [([{'location': self.disk, 'intent': 'appliance'},
               {'location': second, 'intent': 'appliance'}],
              [{'location': self.ova}])])
        self.module.build(self.options)
        names = [m.name for m, _ in self.readOva()]
        self.assertEqual(names, ['appliance.ovf', 'root-disk1.vmdk',
                                 'data-disk2.vmdk', 'appliance.mf'])

    def test_build_unknown_firmware_fails_without_writing_an_archive(self):
        self.options['firmware'] = 'openfirmware'
        self.assertIsNone(self.module.build(self.options))
        self.assertEqual(self.module.log.results, ['failed'])
        self.assertFalse(os.path.exists(self.ova))

    def test_build_unknown_manifest_format_fails_without_writing_an_archive(self):
        self.options['manifest-format'] = 'md5'
        self.assertIsNone(self.module.build(self.options))
        self.assertEqual(self.module.log.results, ['failed'])
        self.assertFalse(os.path.exists(self.ova))

    def test_build_missing_disk_capacity_fails(self):
        del self.options['disk-capacity-appliance']
        with self.assertRaises(KeyError):
            self.module.build(self.options)
        self.assertEqual(self.module.log.results, ['failed'])

    def test_build_missing_disk_format_fails(self):
        del self.options['disk-format-appliance']
        with self.assertRaises(KeyError):
            self.module.build(self.options)
        self.assertEqual(self.module.log.results, ['failed'])

    def test_build_unknown_disk_format_lists_the_valid_formats(self):
        self.options['disk-format-appliance'] = 'Floppy'
        with self.assertRaises(KeyError):
            self.module.build(self.options)
        self.assertIn('VMDK Stream Optimized', self.module.log.messages('error'))

    def test_build_used_size_is_reported_as_populated_size(self):
        self.module.mapping.specs[0][0][0]['used-size'] = 1234
        self.module.build(self.options)
        ovf = dict((m.name, d) for m, d in self.readOva())['appliance.ovf'].decode()
        self.assertIn('ovf:populatedSize="1234"', ovf)

    def test_package_vm_builds_the_archive(self):
        self.module.package_vm(self.options)
        self.assertTrue(os.path.exists(self.ova))

    def test_clean_passes(self):
        self.module.clean(self.options)
        self.assertEqual(self.module.log.results, ['passed'])


if __name__ == '__main__':
    unittest.main()
