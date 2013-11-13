# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

# <pep8 compliant>

# Script copyright (C) Campbell Barton, Bastien Montagne


import datetime
import math
import os
import time
import collections.abc

import bpy
from mathutils import Vector, Matrix

from . import encode_bin


# "Constants"
FBX_HEADER_VERSION = 1003
FBX_VERSION = 7300


# Helpers to generate/manage IDs
# ID class (mere int).
class UID(int):
    pass


# IDs storage (singleton).
class FBXID(collections.abc.Mapping):
    _fbxid = None

    def __new__(cls):
        if cls._fbxid is not None:
            return cls._fbxid
        return super(FBXID, cls).__new__(cls)

    def __init__(self):
        cls = self.__class__
        if cls._fbxid is not None:
            assert(self == cls._fbxid)
            return

        self.keys_to_uids = {}
        self.uids_to_keys = {}
        cls._fbxid = self

    def _value_to_uid(self, value):
        # TODO: check this is robust enough for our needs!
        # Note: we assume we have already checked the related key wasn't yet in FBXID!
        # XXX FBX's int64 is signed, this *may* be a problem (or not...).
        if isinstance(value, int) and 0 <= value < 2**64:
            # We can use value directly as id!
            uid = value
        else:
            uid = hash(value)
        # Make sure our uid *is* unique.
        while uid in self.uids_to_keys:
            uid += 1
        return UID(uid)

    def add(self, key, value=None):
        """If value is None, key is used as value as well. Return the id"""
        if key in self.keys_to_uids:
            return self.keys_to_uids[key]
        uid = self._value_to_uid(value)
        self.keys_to_uids[key] = uid
        self.uids_to_keys[uid] = key
        return uid

    # Mapping API
    def __len__(self):
        return len(self.keys_to_uids)

    def __getitem__(self, key):
        if isinstance(key, UID):
            return self.uids_to_keys[key]
        return self.keys_to_uids[key]

    def __iter__(self):
        # No choice here, we can't be smart, always iter over keys_to_uid...
        return iter(self.keys_to_uids)


# Helpers to generate single-data elements.
# Note: elem may be None, in this case the element is not added to any parent.
def elem_empty(elem, name):
    sub_elem = encode_bin.FBXElem(name)
    if elem is not None:
        elem.elems.append(sub_elem)
    return sub_elem


def elem_properties(elem):
    return elem_empty(elem, b"Properties70")


def _elem_data_single(elem, name, value, func_name):
    sub_elem = elem_empty(elem, name)
    getattr(sub_elem, func_name)(value)
    return sub_elem


def elem_data_single_bool(elem, name, value):
    return _elem_data_single(elem, name, value, "add_bool")


def elem_data_single_int16(elem, name, value):
    return _elem_data_single(elem, name, value, "add_int16")


def elem_data_single_int32(elem, name, value):
    return _elem_data_single(elem, name, value, "add_int32")


def elem_data_single_int64(elem, name, value):
    return _elem_data_single(elem, name, value, "add_int64")


def elem_data_single_float32(elem, name, value):
    return _elem_data_single(elem, name, value, "add_float32")


def elem_data_single_float64(elem, name, value):
    return _elem_data_single(elem, name, value, "add_float64")


def elem_data_single_bytes(elem, name, value):
    return _elem_data_single(elem, name, value, "add_bytes")


def elem_data_single_string(elem, name, value):
    return _elem_data_single(elem, name, value, "add_string")


def elem_data_single_string_unicode(elem, name, value):
    return _elem_data_single(elem, name, value, "add_string_unicode")


def elem_data_single_bool_array(elem, name, value):
    return _elem_data_single(elem, name, value, "add_bool_array")


def elem_data_single_int32_array(elem, name, value):
    return _elem_data_single(elem, name, value, "add_int32_array")


def elem_data_single_int64_array(elem, name, value):
    return _elem_data_single(elem, name, value, "add_int64_array")


def elem_data_single_float32_array(elem, name, value):
    return _elem_data_single(elem, name, value, "add_float32_array")


def elem_data_single_float64_array(elem, name, value):
    return _elem_data_single(elem, name, value, "add_float64_array")


def elem_data_single_byte_array(elem, name, value):
    return _elem_data_single(elem, name, value, "add_byte_array")


# Helpers to generate standard FBXProperties70 properties...
# XXX Looks like there can be various variations of formats here... Will have to be checked ultimately!
def elem_props_set_bool(elem, name, value):
    p = elem_data_single_string(elem, b"P", name)
    p.add_string(b"bool")
    p.add_string(b"")
    p.add_string(b"")
    p.add_bool(value)


def elem_props_set_integer(elem, name, value):
    p = elem_data_single_string(elem, b"P", name)
    p.add_string(b"int")
    p.add_string(b"Integer")
    p.add_string(b"")
    p.add_int32(value)


def elem_props_set_enum(elem, name, value):
    p = elem_data_single_string(elem, b"P", name)
    p.add_string(b"enum")
    p.add_string(b"")
    p.add_string(b"")
    p.add_int32(value)


def elem_props_set_number(elem, name, value):
    p = elem_data_single_string(elem, b"P", name)
    p.add_string(b"double")
    p.add_string(b"Number")
    p.add_string(b"")
    p.add_float64(value)


def elem_props_set_color_rgb(elem, name, value):
    p = elem_data_single_string(elem, b"P", name)
    p.add_string(b"ColorRGB")
    p.add_string(b"Color")
    p.add_string(b"")
    p.add_float64(value[0])
    p.add_float64(value[1])
    p.add_float64(value[2])


def elem_props_set_string_ex(elem, name, value, subtype):
    p = elem_data_single_string(elem, b"P", name)
    p.add_string(b"KString")
    p.add_string(subtype)
    p.add_string(b"")
    p.add_string_unicode(value)


def elem_props_set_string(elem, name, value):
    elem_props_set_string_ex(elem, name, value, b"")


def elem_props_set_string_url(elem, name, value):
    elem_props_set_string_ex(elem, name, value, b"Url")


def elem_props_set_timestamp(elem, name, value):
    p = elem_data_single_string(elem, b"P", name)
    p.add_string(b"KTime")
    p.add_string(b"Time")
    p.add_string(b"")
    p.add_int64(value)


def elem_props_set_object(elem, name, value):
    p = elem_data_single_string(elem, b"P", name)
    p.add_string(b"object")
    p.add_string(b"")
    p.add_string(b"")
    # XXX Check this! No value for this prop???
    #p.add_string_unicode(value)


# Various FBX parts generators.
def fbx_header_elements(root, time=None):
    """
    Write boiling code of FBX root.
    time is expected to be a datetime.datetime object, or None (using now() in this case).
    """
    ##### Start of FBXHeaderExtension element.
    header_ext = elem_empty(root, b"FBXHeaderExtension")

    elem_data_single_int32(header_ext, b"FBXHeaderVersion", FBX_HEADER_VERSION)

    elem_data_single_int32(header_ext, b"FBXVersion", FBX_VERSION)

    # No encryption!
    elem_data_single_int32(header_ext, b"EncryptionType", 0)

    if time is None:
        time = datetime.datetime.now()
    elem = elem_empty(header_ext, b"CreationTimeStamp")
    elem_data_single_int32(elem, b"Version", 1000)
    elem_data_single_int32(elem, b"Year", time.year)
    elem_data_single_int32(elem, b"Month", time.month)
    elem_data_single_int32(elem, b"Day", time.day)
    elem_data_single_int32(elem, b"Hour", time.hour)
    elem_data_single_int32(elem, b"Minute", time.minute)
    elem_data_single_int32(elem, b"Second", time.second)
    elem_data_single_int32(elem, b"Millisecond", time.microsecond * 1000)

    elem_data_single_string_unicode(header_ext, b"Creator", "Blender version %s" % bpy.app.version_string)

    # Skip 'SceneInfo' element for now...

    ##### End of FBXHeaderExtension element.

    # FileID is replaced by dummy value currently...
    elem_data_single_bytes(root, b"FileId", b"FooBar")

    # CreationTime is replaced by dummy value currently, but anyway...
    elem_data_single_string_unicode(root, b"CreationTime",
                                    "{:04}-{:02}-{:02} {:02}:{:02}:{:02}:{:03}"
                                    "".format(time.year, time.month, time.day, time.hour, time.minute, time.second,
                                              time.microsecond * 1000))

    elem_data_single_string_unicode(root, b"Creator", "Blender version %s" % bpy.app.version_string)

    ##### Start of GlobalSettings element.
    global_settings = elem_empty(root, b"GlobalSettings")

    elem_data_single_int32(global_settings, b"Version", 1000)

    props = elem_properties(global_settings)
    elem_props_set_integer(props, b"UpAxis", 1)
    elem_props_set_integer(props, b"UpAxisSign", 1)
    elem_props_set_integer(props, b"FrontAxis", 2)
    elem_props_set_integer(props, b"FrontAxisSign", 1)
    elem_props_set_integer(props, b"CoordAxis", 0)
    elem_props_set_integer(props, b"CoordAxisSign", 1)
    elem_props_set_number(props, b"UnitScaleFactor", 1.0)
    elem_props_set_color_rgb(props, b"AmbientColor", (0.0, 0.0, 0.0))
    elem_props_set_string(props, b"DefaultCamera", "")
    # XXX Those time stuff is taken from a file, have no (complete) idea what it means!
    elem_props_set_enum(props, b"TimeMode", 11)
    elem_props_set_timestamp(props, b"TimeSpanStart", 0)
    elem_props_set_timestamp(props, b"TimeSpanStop", 479181389250)

    ##### End of GlobalSettings element.


def fbx_documents_elements(root, name=""):
    """
    Write 'Document' part of FBX root.
    Seems like FBX support multiple documents, but until I find examples of such, we'll stick to single doc!
    time is expected to be a datetime.datetime object, or None (using now() in this case).
    """
    fbxid = FBXID()

    ##### Start of Documents element.
    docs = elem_empty(root, b"Documents")

    elem_data_single_int32(docs, b"Count", 1)

    doc_uid = fbxid.add("__FBX_Document__" + name)
    doc = elem_data_single_int64(docs, b"Document", doc_uid)
    doc.add_string(b"")
    doc.add_string_unicode(name)

    props = elem_properties(doc)
    elem_props_set_object(props, b"SourceObject", "")
    elem_props_set_string(props, b"ActiveAnimStackName", "")

    # XXX Probably some kind of offset? Binary one?
    #     Anyway, as long as we have only one doc, probably not an issue.
    elem_data_single_int64(doc, b"RootNode", 0)


def fbx_references_elements(root):
    """
    Have no idea what references are in FBX currently... Just writing empty element.
    """
    docs = elem_empty(root, b"References")


def fbx_definitions_elements(root):
    """
    Templates definitions. Only used by Objects data afaik (apart from dummy GlobalSettings one).
    """
    docs = elem_empty(root, b"Definitions")


def fbx_objects_elements(root):
    """
    Data (objects, geometry, material, textures, armatures, etc.
    """
    docs = elem_empty(root, b"Objects")


def fbx_connections_elements(root):
    """
    Relations between Objects (which material uses which texture, and so on).
    """
    docs = elem_empty(root, b"Connections")


def fbx_takes_elements(root):
    """
    Animations. Have yet to check how this work...
    """
    docs = elem_empty(root, b"Takes")


# This func can be called with just the filepath
def save_single(operator, scene, filepath="",
                global_matrix=None,
                context_objects=None,
                object_types={'EMPTY', 'CAMERA', 'LAMP', 'ARMATURE', 'MESH'},
                use_mesh_modifiers=True,
                mesh_smooth_type='FACE',
                use_armature_deform_only=False,
                use_anim=True,
                use_anim_optimize=True,
                anim_optimize_precision=6,
                use_anim_action_all=False,
                use_metadata=True,
                path_mode='AUTO',
                use_mesh_edges=True,
                use_default_take=True,
                **kwargs
                ):

    import bpy_extras.io_utils

    print('\nFBX export starting... %r' % filepath)
    start_time = time.process_time()

    # Only used for camera and lamp rotations
    mtx_x90 = Matrix.Rotation(math.pi / 2.0, 3, 'X')
    # Used for mesh and armature rotations
    mtx4_z90 = Matrix.Rotation(math.pi / 2.0, 4, 'Z')

    if global_matrix is None:
        global_matrix = Matrix()
        global_scale = 1.0
    else:
        global_scale = global_matrix.median_scale

    # Use this for working out paths relative to the export location
    base_src = os.path.dirname(bpy.data.filepath)
    base_dst = os.path.dirname(filepath)

    # collect images to copy
    copy_set = set()

    root = elem_empty(None, b"")  # Root element has no id, as it is not saved per se!

    # Mostly FBXHeaderExtension and GlobalSettings.
    fbx_header_elements(root)

    # Documents and References are pretty much void currently.
    fbx_documents_elements(root, scene.name)
    fbx_references_elements(root)

    # Templates definitions.
    fbx_definitions_elements(root)

    # Actual data.
    fbx_objects_elements(root)

    # How data are inter-connected.
    fbx_connections_elements(root)

    # Animation.
    fbx_takes_elements(root)

    # And we are down, we can write the whole thing!
    encode_bin.write(filepath, root, FBX_VERSION)

    # copy all collected files.
    bpy_extras.io_utils.path_reference_copy(copy_set)

    print('export finished in %.4f sec.' % (time.process_time() - start_time))
    return {'FINISHED'}


# defaults for applications, currently only unity but could add others.
def defaults_unity3d():
    return dict(global_matrix=Matrix.Rotation(-math.pi / 2.0, 4, 'X'),
                use_selection=False,
                object_types={'ARMATURE', 'EMPTY', 'MESH'},
                use_mesh_modifiers=True,
                use_armature_deform_only=True,
                use_anim=True,
                use_anim_optimize=False,
                use_anim_action_all=True,
                batch_mode='OFF',
                use_default_take=True,
                )


def save(operator, context,
         filepath="",
         use_selection=False,
         batch_mode='OFF',
         use_batch_own_dir=False,
         **kwargs
         ):
    """
    This is a wrapper around save_single, which handles multi-scenes (or groups) cases, when batch-exporting a whole
    .blend file.
    """

    ret = None

    org_mode = None
    if context.active_object and context.active_object.mode != 'OBJECT' and bpy.ops.object.mode_set.poll():
        org_mode = context.active_object.mode
        bpy.ops.object.mode_set(mode='OBJECT')

    if batch_mode == 'OFF':
        kwargs_mod = kwargs.copy()
        if use_selection:
            kwargs_mod["context_objects"] = context.selected_objects
        else:
            kwargs_mod["context_objects"] = context.scene.objects

        ret = save_single(operator, context.scene, filepath, **kwargs_mod)
    else:
        fbxpath = filepath

        prefix = os.path.basename(fbxpath)
        if prefix:
            fbxpath = os.path.dirname(fbxpath)

        if batch_mode == 'GROUP':
            data_seq = bpy.data.groups
        else:
            data_seq = bpy.data.scenes

        # call this function within a loop with BATCH_ENABLE == False
        # no scene switching done at the moment.
        # orig_sce = context.scene

        new_fbxpath = fbxpath  # own dir option modifies, we need to keep an original
        for data in data_seq:  # scene or group
            newname = "_".join((prefix, bpy.path.clean_name(data.name)))

            if use_batch_own_dir:
                new_fbxpath = os.path.join(fbxpath, newname)
                # path may already exist
                # TODO - might exist but be a file. unlikely but should probably account for it.

                if not os.path.exists(new_fbxpath):
                    os.makedirs(new_fbxpath)

            filepath = os.path.join(new_fbxpath, newname + '.fbx')

            print('\nBatch exporting %s as...\n\t%r' % (data, filepath))

            if batch_mode == 'GROUP':  # group
                # group, so objects update properly, add a dummy scene.
                scene = bpy.data.scenes.new(name="FBX_Temp")
                scene.layers = [True] * 20
                # bpy.data.scenes.active = scene # XXX, cant switch
                for ob_base in data.objects:
                    scene.objects.link(ob_base)

                scene.update()
                # TODO - BUMMER! Armatures not in the group wont animate the mesh
            else:
                scene = data

            kwargs_batch = kwargs.copy()
            kwargs_batch["context_objects"] = data.objects

            save_single(operator, scene, filepath, **kwargs_batch)

            if batch_mode == 'GROUP':
                # remove temp group scene
                bpy.data.scenes.remove(scene)

        # no active scene changing!
        # bpy.data.scenes.active = orig_sce

        ret = {'FINISHED'}  # so the script wont run after we have batch exported.

    if context.active_object and org_mode and bpy.ops.object.mode_set.poll():
        bpy.ops.object.mode_set(mode=org_mode)

    return ret
