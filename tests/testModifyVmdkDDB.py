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
"""ModifyVmdkDDB edits the descriptor of a VMDK in place.  In Python 3 the
file contents are bytes while the section options are str, so these tests
build a real VMDK-shaped file (magic, header, padded DDB, grain data) and
check what ends up on disk."""
import os
import shutil
import tempfile
import unittest

from tests import csmake_alias
csmake_alias.install()

from CsmakeModules.ModifyVmdkDDB import ModifyVmdkDDB
from tests.helpers import FakeLog, read_bytes

DDB_SIZE = ModifyVmdkDDB.DDB_READ_SIZE
HEADER = b"KDMV" + bytes(i % 251 + 1 for i in range(0x1fc))   # 0x200 bytes
DESCRIPTOR = (b'ddb.adapterType = "lsilogic"\n'
              b'ddb.geometry.cylinders = "1024"\n'
              b'ddb.virtualHWVersion = "4"\n')
# What follows the descriptor region: must survive an edit untouched
GRAIN_DATA = bytes(range(256)) * 16


def makeVmdk(path, descriptor=DESCRIPTOR, ddbSize=DDB_SIZE, magic=b"KDMV"):
    ddb = descriptor + b'\0' * (ddbSize - len(descriptor))
    with open(path, 'wb') as vmdk:
        vmdk.write(magic + HEADER[4:])
        vmdk.write(ddb)
        vmdk.write(GRAIN_DATA)


class FakeMapping:
    def __init__(self, froms, tos):
        self.pairs = [(froms, tos)]

    def iterfiles(self):
        return iter(self.pairs)


class TestModifyVmdkDDB(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='vmdktest')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, 'disk.vmdk')
        self.module = object.__new__(ModifyVmdkDDB)
        self.module.log = FakeLog()

    def readDdb(self):
        data = read_bytes(self.path)
        return data[0x200:0x200 + DDB_SIZE]

    def runBuild(self, options):
        self.module.mapping = FakeMapping([self.path], [self.path])
        return self.module.build(options)

    def test_load_accepts_a_real_vmdk_and_keeps_bytes(self):
        makeVmdk(self.path)
        self.assertTrue(self.module._loadDDB(self.path))
        self.assertIsInstance(self.module.ddb, bytes)
        self.assertEqual(len(self.module.ddb), DDB_SIZE)
        self.assertTrue(self.module.ddb.startswith(DESCRIPTOR))
        self.assertEqual(self.module.log.results, [])

    def test_load_rejects_files_without_the_vmdk_magic(self):
        makeVmdk(self.path, magic=b"NOPE")
        self.assertFalse(self.module._loadDDB(self.path))
        self.assertEqual(self.module.log.results, ['failed'])
        self.assertIn('is not a VMDK file', self.module.log.messages('error')[0])

    def test_load_rejects_a_ddb_section_that_is_not_nul_terminated(self):
        makeVmdk(self.path, descriptor=b'x' * DDB_SIZE)
        self.assertFalse(self.module._loadDDB(self.path))
        self.assertEqual(self.module.log.results, ['failed'])

    def test_replace_keeps_the_section_size_whether_it_grows_or_shrinks(self):
        makeVmdk(self.path)
        self.module._loadDDB(self.path)
        for old, new in [('lsilogic', 'pvscsi'),                  # shrinks
                         ('pvscsi', 'lsilogic-with-a-longer-name')]:  # grows
            self.assertTrue(self.module._replace(old, new))
            self.assertEqual(len(self.module.ddb), DDB_SIZE)
            self.assertIn(new.encode(), self.module.ddb)
            self.assertTrue(self.module.ddb.endswith(b'\0'))

    def test_replace_of_missing_text_fails(self):
        makeVmdk(self.path)
        self.module._loadDDB(self.path)
        self.assertFalse(self.module._replace('not in the ddb', 'x'))
        self.assertEqual(self.module.log.results, ['failed'])

    def test_append_fills_the_nul_padding_and_terminates_the_line(self):
        makeVmdk(self.path)
        self.module._loadDDB(self.path)
        self.assertTrue(self.module._append('ddb.toolsVersion = "2147483647"'))
        self.assertEqual(len(self.module.ddb), DDB_SIZE)
        self.assertTrue(self.module.ddb.startswith(
            DESCRIPTOR + b'ddb.toolsVersion = "2147483647"\n\0'))

    def test_build_round_trip_edits_only_the_ddb_section_on_disk(self):
        makeVmdk(self.path)
        before = read_bytes(self.path)
        options = {
            'substitute_1': 'ddb.adapterType = "lsilogic"\n'
                            'ddb.adapterType = "pvscsi"',
            'append': 'ddb.uuid = "60 00 C2 90"',
            '**some-csmake-internal': 'ignored',
        }
        self.assertTrue(self.runBuild(options))
        self.assertEqual(self.module.log.results, ['passed'])

        after = read_bytes(self.path)
        self.assertEqual(len(after), len(before))               # padding kept
        self.assertEqual(after[:0x200], before[:0x200])         # header
        self.assertEqual(after[0x200 + DDB_SIZE:],              # grain data
                         before[0x200 + DDB_SIZE:])
        ddb = self.readDdb()
        self.assertTrue(ddb.startswith(
            b'ddb.adapterType = "pvscsi"\n'
            b'ddb.geometry.cylinders = "1024"\n'
            b'ddb.virtualHWVersion = "4"\n'
            b'ddb.uuid = "60 00 C2 90"\n\0'))
        self.assertNotIn(b'lsilogic', ddb)
        self.assertEqual(ddb.rstrip(b'\0').count(b'\n'), 4)

    def test_build_leaves_the_file_alone_when_a_substitution_fails(self):
        makeVmdk(self.path)
        before = read_bytes(self.path)
        self.assertFalse(self.runBuild(
            {'substitute_1': 'no such line\nreplacement'}))
        self.assertEqual(read_bytes(self.path), before)


if __name__ == '__main__':
    unittest.main()
