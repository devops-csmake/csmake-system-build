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
"""ConvertVirtualImage picks qemu-img or vbox-img for each 1-1 mapping and
builds the command line.  The converter and the file checks are mocked."""
from unittest import mock

from tests import csmake_alias
csmake_alias.install()

from CsmakeModules.ConvertVirtualImage import ConvertVirtualImage
from tests.helpers import FakeMapping, FakePaths, SubprocessTestCase, new_module

SRC, DST = '/images/in.img', '/images/out.img'


def spec(fromtype, totype, **extra):
    source = {'type': fromtype + '-image', 'location': SRC}
    source.update(extra)
    return ([source], [{'type': totype + '-image', 'location': DST}])


class ConvertTestCase(SubprocessTestCase):

    def setUp(self):
        SubprocessTestCase.setUp(self)
        self.paths = FakePaths(self)

    def convert(self, specs, **options):
        module = new_module(ConvertVirtualImage, log=self.log,
                            mapping=FakeMapping(specs))
        return module.build(options)


class TestToolSelection(ConvertTestCase):

    def test_build_raw_to_vmdk_uses_vbox_img_streaming(self):
        self.assertTrue(self.convert([spec('raw', 'vmdk')]))
        self.assertEqual(self.sp.all_cmds(), [[
            'vbox-img', 'convert', '--srcformat', 'RAW', '--dstformat', 'VMDK',
            '--srcfilename', SRC, '--dstfilename', DST, '--variant', 'Stream']])
        self.assertEqual(self.log.results, ['passed'])

    def test_build_qcow2_to_vmdk_uses_qemu_img(self):
        self.convert([spec('qcow2', 'vmdk')])
        self.assertEqual(self.sp.all_cmds(), [[
            'qemu-img', 'convert', '-c', '-f', 'qcow2', SRC, '-O', 'vmdk', DST]])

    def test_build_raw_to_qcow2_uses_qemu_img(self):
        self.convert([spec('raw', 'qcow2')])
        self.assertEqual(self.sp.all_cmds()[0][:2], ['qemu-img', 'convert'])

    def test_build_other_formats_are_lower_cased_for_qemu(self):
        self.convert([spec('vhdx', 'vpc')])
        self.assertEqual(self.sp.all_cmds()[0][-5:], ['vhdx', SRC, '-O', 'vpc', DST])

    def test_build_tool_option_overrides_the_choice(self):
        self.convert([spec('raw', 'vmdk')], tool=' qemu-img ')
        self.assertEqual(self.sp.all_cmds()[0][0], 'qemu-img')
        self.sp.calls.clear()
        self.convert([spec('raw', 'qcow2')], tool='vbox-img')
        self.assertEqual(self.sp.all_cmds()[0][0], 'vbox-img')


class TestCommandOptions(ConvertTestCase):

    def test_build_compress_false_drops_the_compression_flag(self):
        self.convert([spec('raw', 'qcow2')], compress=' False ')
        self.assertNotIn('-c', self.sp.all_cmds()[0])

    def test_build_compress_other_values_keep_compression(self):
        self.convert([spec('raw', 'qcow2')], compress='no')
        self.assertIn('-c', self.sp.all_cmds()[0])

    def test_build_extra_options_are_shell_split_and_appended(self):
        self.convert([spec('raw', 'qcow2')],
                     extra='-o "cluster size=64k" -p ')
        self.assertEqual(self.sp.all_cmds()[0][-3:],
                         ['-o', 'cluster size=64k', '-p'])

    def test_build_extra_options_with_non_ascii_text(self):
        self.convert([spec('raw', 'qcow2')], extra="-o comment='déjà'")
        self.assertEqual(self.sp.all_cmds()[0][-2:], ['-o', 'comment=déjà'])

    def test_build_vbox_extra_options_follow_the_variant(self):
        self.convert([spec('raw', 'vmdk')], extra='--foo bar')
        self.assertEqual(self.sp.all_cmds()[0][-3:], ['Stream', '--foo', 'bar'])


class TestOutputHandling(ConvertTestCase):

    def test_build_vbox_removes_an_existing_destination_first(self):
        self.paths.exists.add(DST)
        with mock.patch('os.remove') as remove:
            self.convert([spec('raw', 'vmdk')])
        remove.assert_called_once_with(DST)

    def test_build_vbox_leaves_a_missing_destination_alone(self):
        with mock.patch('os.remove') as remove:
            self.convert([spec('raw', 'vmdk')])
        remove.assert_not_called()

    def test_build_qemu_does_not_remove_the_destination(self):
        self.paths.exists.add(DST)
        with mock.patch('os.remove') as remove:
            self.convert([spec('raw', 'qcow2')])
        remove.assert_not_called()

    def test_build_copies_used_size_onto_the_destination(self):
        source, dest = spec('raw', 'qcow2', **{'used-size': 12345})
        self.convert([(source, dest)])
        self.assertEqual(dest[0]['used-size'], 12345)

    def test_build_without_used_size_leaves_the_destination_alone(self):
        source, dest = spec('raw', 'qcow2')
        self.convert([(source, dest)])
        self.assertNotIn('used-size', dest[0])


class TestFailures(ConvertTestCase):

    def test_build_converter_failure_fails_the_section(self):
        self.sp.on('qemu-img', rc=1)
        self.assertIsNone(self.convert([spec('raw', 'qcow2')]))
        self.assertEqual(self.log.results, ['failed'])
        self.assertIn('Convert of the Virtual Image failed', self.log.messages('error'))

    def test_build_failure_stops_before_later_mappings(self):
        self.sp.on('qemu-img', rc=1)
        self.convert([spec('raw', 'qcow2'), spec('raw', 'qcow2')])
        self.assertEqual(len(self.sp.cmds('qemu-img')), 1)

    def test_build_many_to_one_mapping_is_rejected(self):
        source, dest = spec('raw', 'qcow2')
        source.append(dict(source[0]))
        self.assertIsNone(self.convert([(source, dest)]))
        self.assertEqual(self.log.results, ['failed'])
        self.assertEqual(self.sp.calls, [])

    def test_build_one_to_many_mapping_is_rejected(self):
        source, dest = spec('raw', 'qcow2')
        dest.append(dict(dest[0]))
        self.assertIsNone(self.convert([(source, dest)]))
        self.assertEqual(self.log.results, ['failed'])

    def test_build_all_mappings_are_converted_in_order(self):
        self.convert([spec('raw', 'qcow2'), spec('raw', 'vmdk')])
        self.assertEqual([cmd[0] for cmd in self.sp.all_cmds()],
                         ['qemu-img', 'vbox-img'])

    def test_build_empty_mapping_passes_without_running_anything(self):
        self.assertTrue(self.convert([]))
        self.assertEqual(self.sp.calls, [])
        self.assertEqual(self.log.results, ['passed'])

    def test_package_vm_delegates_to_build(self):
        module = new_module(ConvertVirtualImage, log=self.log,
                            mapping=FakeMapping([spec('raw', 'qcow2')]))
        self.assertTrue(module.package_vm({}))
        self.assertEqual(len(self.sp.calls), 1)
