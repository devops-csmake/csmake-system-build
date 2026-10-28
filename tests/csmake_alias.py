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
"""Test-only shim: plugin modules say 'from Csmake.X import Y' but the
installed csmake ships the package as CsmakeCore.  Alias one to the other
(same module objects) so the modules can be imported under test.
Call install() before importing anything from CsmakeModules."""
import importlib
import importlib.abc
import importlib.util
import os
import sys
import unittest


class _CsmakeAliasFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path, target=None):
        if fullname.startswith('Csmake.'):
            return importlib.util.spec_from_loader(fullname, self)
        return None

    def create_module(self, spec):
        return importlib.import_module(
            'CsmakeCore.' + spec.name.split('.', 1)[1])

    def exec_module(self, module):
        pass


def install():
    if 'Csmake' in sys.modules or importlib.util.find_spec('Csmake'):
        return
    if importlib.util.find_spec('CsmakeCore') is None:
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sibling = os.path.join(os.path.dirname(repo), 'csmake')
        if not os.path.isdir(os.path.join(sibling, 'CsmakeCore')):
            raise unittest.SkipTest("csmake core not found")
        # Appended, so the checkout under test always wins for CsmakeModules
        sys.path.append(sibling)
    sys.modules['Csmake'] = importlib.import_module('CsmakeCore')
    sys.meta_path.insert(0, _CsmakeAliasFinder())
