# <copyright>
# (c) Copyright 2017 Hewlett Packard Enterprise Development LP
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
from CsmakeCore.CsmakeModule import CsmakeModule
import shutil
import os.path
import subprocess

class ModifyVmdkDDB(CsmakeModule):
    """Purpose: To modify a DDB section of a VMDK.
       Library: csmake-system-build
       Maps: 1-1 only, from and to must be the same file
       Phases: build
       Flags:
           substitute_<n> - Specifies a substitution of a line for
               a new line.  <n> is really any unique value to allow
               for multiple substitutions
           delete_<n> - Specifies a statement in the ddb to remove completely
               (NOT YET IMPLEMENTED)
           append - Specifies statements to add to the end of
                    the DDB.  Use newlines to separate between statements
    """

    DDB_READ_SIZE=0x2000

    def _loadDDB(self, filepath):
        with open(filepath, 'rb') as vmdkfile:
            magic = vmdkfile.read(4)
            if magic != b"\x4b\x44\x4d\x56":
                self.log.error("File '%s' is not a VMDK file", filepath)
                self.log.failed()
                return False
            #Get the vmdk header file
            #TODO: Be more precise with the VMDK file format
            #      This code is just based on what's commonly known
            #      with some guard rails
            #      But it would be better to follow the full standard
            #      - it's just not 100% straightforward....
            vmdkfile.seek(0x200) #offset into the ddb
            self.ddb = vmdkfile.read(ModifyVmdkDDB.DDB_READ_SIZE) #Pretty safe number
                                             #The ddb section is ~0x10000 padded
            if len(self.ddb) != ModifyVmdkDDB.DDB_READ_SIZE or self.ddb[-1:] != b'\0':
                self.log.error("Unexpected behavior, punting - attempted to read 8196B of the dde section and either overran the section, didn't read far enough or didn't have enough memory to read the full section all at once")
                self.log.failed()
                return False
            return True

    def _writeDDB(self, filepath):
        with open(filepath, "r+b") as vmdkfile:
            vmdkfile.seek(0x200)
            vmdkfile.write(self.ddb)
        return True

    def _replace(self, fromText, toText):
        fromBytes = fromText.encode('utf-8') if isinstance(fromText, str) else fromText
        toBytes = toText.encode('utf-8') if isinstance(toText, str) else toText
        newText = self.ddb.replace(fromBytes, toBytes)
        if newText == self.ddb:
            self.log.error("The value '%s' was not replaced", fromText)
            self.log.failed()
            return False
        self.ddb = newText
        if len(self.ddb) > ModifyVmdkDDB.DDB_READ_SIZE:
            self.ddb = self.ddb[:ModifyVmdkDDB.DDB_READ_SIZE]
        else:
            self.ddb = self.ddb + (ModifyVmdkDDB.DDB_READ_SIZE-len(self.ddb)) * b'\0'
        return True

    def _append(self, appendlines):
        if appendlines[-1] != '\n':
            appendlines = appendlines + '\n'
        appendbytes = appendlines.encode('utf-8') if isinstance(appendlines, str) else appendlines
        self.ddb = self.ddb.replace(len(appendbytes)*b'\0', appendbytes, 1)
        if len(self.ddb) != ModifyVmdkDDB.DDB_READ_SIZE:
            self.log.error("Replace text overran buffer")
            self.log.failed()
            return False
        return True

    def build(self, options):
        for froms, tos in self.mapping.iterfiles():
            if len(froms) > 1 or len(tos) > 1:
                self.log.error("The files mapped in this section must be a single file to a single file (1-1)")
                self.log.failed()
                return False
            if os.path.realpath(os.path.abspath(froms[0])) \
                != os.path.realpath(os.path.abspath(tos[0])):
                self.log.error("This section modifies files in-place. The from and to files in the mapping must be the same")
                self.log.error("   From: %s", froms[0])
                self.log.error("   To: %s", tos[0])
                self.log.failed()
                return False
            if not self._loadDDB(froms[0]):
                return False
            for key, value in options.items():
                if key == 'append':
                    if not self._append(value):
                        return False
                elif key.startswith('substitute_'):
                    parts = value.strip().split('\n')
                    if len(parts) != 2:
                        self.log.error("The format for a substitution is:")
                        self.log.error("  substitute_<n>=<old entry>")
                        self.log.error("     <new entry>")
                        self.log.error("What was given was:")
                        self.log.error("%s=%s", key, value)
                        self.log.failed()
                        return False
                    if not self._replace(parts[0], parts[1]):
                        return False
                elif key.startswith('delete_'):
                    self.log.error("Delete not implemented")
                    self.log.failed()
                    return False
                else:
                    if not key.startswith('**'):
                        self.log.error("Option '%s': action is not defined", key)
                        self.log.failed()
                        return False
            if not self._writeDDB(tos[0]):
                return False
        self.log.passed()
        return True
