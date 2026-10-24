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
"""urlparse -> urllib.parse in HLinuxConfigApt: the host of the apt URL ends
up in the generated apt.conf."""
import os
import unittest

from tests import csmake_alias
csmake_alias.install()

from tests.helpers import FakeBinTestCase

hlinuxSkipReason = ''
try:
    # HLinuxConfigApt builds on ShellEnv, which lives in csmake core
    from CsmakeModules.HLinuxConfigApt import HLinuxConfigApt
except ImportError as importFailure:
    # Only a missing csmake core module is a reason to skip; any other
    # import problem in HLinuxConfigApt itself should fail loudly.
    if not (importFailure.name or '').startswith(
            ('CsmakeModules.ShellEnv', 'CsmakeCore')):
        raise
    HLinuxConfigApt = None
    hlinuxSkipReason = "csmake core's ShellEnv is not importable: %s" % importFailure


@unittest.skipIf(HLinuxConfigApt is None, hlinuxSkipReason)
class TestHLinuxConfigApt(FakeBinTestCase):

    def test_default_writes_apt_files_using_the_url_host(self):
        module = object.__new__(HLinuxConfigApt)
        module.log = self.log
        config = os.path.join(self.tmp, 'config')
        os.mkdir(config)

        result = module.default({
            'config': config, 'aptURL': 'http://apt.example.com:3142/mirror',
            'archive': '2014/repo.1', 'release': 'cattleprod',
            'sections': 'main contrib', 'debootstrap': '/usr/sbin/debootstrap'})

        with open(os.path.join(config, 'apt', 'apt.conf')) as conf:
            self.assertEqual(
                conf.read(), 'Acquire::http::Proxy::apt.example.com:3142 DIRECT;\n')
        with open(os.path.join(config, 'apt', 'sources.list')) as sources:
            self.assertEqual(
                sources.read(), 'deb http://apt.example.com:3142/mirror/'
                                'hLinuxArchive/2014/repo.1 cattleprod main contrib\n')
        self.assertEqual(
            result['DIB_DISTRIBUTION_MIRROR'],
            'http://apt.example.com:3142/mirror/hLinuxArchive/2014/repo.1')


if __name__ == '__main__':
    unittest.main()
