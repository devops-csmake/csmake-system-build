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
"""Every Python file in the repo must compile under Python 3.  Cheap guard
against Python 2 syntax (print statements, 'except X, e', mixed tabs and
spaces) creeping back in."""
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pythonFiles():
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [d for d in dirnames if d not in ('.git', '__pycache__')]
        for filename in filenames:
            if filename.endswith('.py'):
                yield os.path.join(dirpath, filename)


class TestEveryFileCompiles(unittest.TestCase):

    def test_all_python_files_compile(self):
        files = sorted(pythonFiles())
        self.assertTrue(files)
        for path in files:
            with self.subTest(file=os.path.relpath(path, REPO)):
                with open(path, 'rb') as source:
                    compile(source.read(), path, 'exec')


if __name__ == '__main__':
    unittest.main()
