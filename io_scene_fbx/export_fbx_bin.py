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

import collections
from collections import namedtuple

import bpy
from mathutils import Vector, Matrix

from . import encode_bin


# "Constants"
FBX_VERSION = 7300
FBX_HEADER_VERSION = 1003
FBX_TEMPLATES_VERSION = 100


##### UIDs code. #####

# ID class (mere int).
class UID(int):
    pass


# UIDs storage.
_keys_to_uids = {}
_uids_to_keys = {}


def _key_to_uid(uids, key):
    # TODO: check this is robust enough for our needs!
    # Note: we assume we have already checked the related key wasn't yet in _keys_to_uids!
    # XXX FBX's int64 is signed, this *may* be a problem (or not...).
    if isinstance(key, int) and 0 <= key < 2**64:
        # We can use value directly as id!
        uid = key
    else:
        uid = hash(key)
    # Make sure our uid *is* unique.
    if uid in uids:
        inc = 1 if uid < 2**63 else -1
        while uid in uids:
            uid += inc
            if 0 > uid >= 2**64:
                # Note that this is more that unlikely, but does not harm anyway...
                raise ValueError("Unable to generate an UID for key {}".format(key))
    return UID(uid)


def get_fbxuid_from_key(key):
    """
    Return an UID for given key, which is assumed hasable.
    """
    uid = _keys_to_uids.get(key, None)
    if uid is None:
        uid = _key_to_uid(_uids_to_keys, key)
        _keys_to_uids[key] = uid
        _uids_to_keys[uid] = key
    return uid


# XXX Not sure we'll actually need this one? 
def get_key_from_fbxuid(uid):
    """
    Return the key which generated this uid.
    """
    assert(uid.__class__ == UID)
    return _uids_to_keys.get(uid, None)


# Blender-specific key generators
def get_blenderID_key(bid):
    return "B" + bid.rna_type.name + "::" + bid.name


def get_blender_camera_keys(cam):
    """Return cam + cam switcher keys."""
    key = get_blenderID_key(cam)
    return key, key + "_switcher"


##### Element generators. #####

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


##### Generators for standard FBXProperties70 properties. #####

# Properties definitions, format: (b"type_1", b"type_2", b"type_3", "name_set_value_1", "name_set_value_2", ...)
# XXX Looks like there can be various variations of formats here... Will have to be checked ultimately!
#     Among other things, what are those "A"/"A+"/"AU" codes?
FBX_PROPERTIES_DEFINITIONS = {
    "p_bool": (b"bool", b"", b"", "add_bool"),
    "p_integer": (b"int", b"Integer", b"", "add_int32"),
    "p_enum": (b"enum", b"", b"", "add_int32"),
    "p_number": (b"double", b"Number", b"", "add_float64"),
    "p_visibility": (b"Visibility", b"", b"A+", "add_float64"),
    "p_vector_3d": (b"Vector3D", b"Vector", b"", "add_float64", "add_float64", "add_float64"),
    "p_lcl_translation": (b"Lcl Translation", b"", b"A+", "add_float64", "add_float64", "add_float64"),
    "p_lcl_rotation": (b"Lcl Rotation", b"", b"A+", "add_float64", "add_float64", "add_float64"),
    "p_lcl_scaling": (b"Lcl Scaling", b"", b"A+", "add_float64", "add_float64", "add_float64"),
    "p_color_rgb": (b"ColorRGB", b"Color", b"", "add_float64", "add_float64", "add_float64"),
    "p_string": (b"KString", b"", b"", "add_string_unicode"),
    "p_string_url": (b"KString", b"Url", b"", "add_string_unicode"),
    "p_timestamp": (b"KTime", b"Time", b"", "add_int64"),
    "p_object": (b"object", b"", b""),  # XXX Check this! No value for this prop???
}


def elem_props_set(elem, ptype, name, value=None):
    p = elem_data_single_string(elem, b"P", name)
    ptype = FBX_PROPERTIES_DEFINITIONS[ptype]
    for t in ptype[:3]:
        p.add_string(t)
    if len(ptype) == 4:
        getattr(p, ptype[3])(value)
    elif len(ptype) > 4:
        # We assume value is iterable, else it's a bug!
        for callback, val in zip(ptype[3:], value):
            getattr(p, callback)(val)


##### Templates #####
# TODO: check all those "default" values, they should match Blender's default as much as possible, I guess?

FBXTemplate = namedtuple("FBXTemplate", ("type_name", "prop_type_name", "properties", "nbr_users"))


def fbx_template_generate(root, fbx_template):
    template = elem_data_single_string(root, b"ObjectType", b"Model")
    elem_data_single_int32(template, b"Count", fbx_template.nbr_users)

    if fbx_template.properties:
        elem = elem_data_single_string(template, b"PropertyTemplate", fbx_template.prop_type_name)
        props = elem_properties(elem)
        for name, (value, ptype) in fbx_template.properties.items():
            elem_props_set(props, ptype, name, value)


def fbx_template_def_globalsettings(override_defaults={}, nbr_users=0):
    props = override_defaults  # No properties, by default.
    return FBXTemplate(b"GlobalSettings", b"", props, nbr_users)


def fbx_template_def_model(override_defaults={}, nbr_users=0):
    props = {
        b"QuaternionInterpolate": (False, "p_bool"),
        b"RotationOffset": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"RotationPivot": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"ScalingOffset": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"ScalingPivot": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"TranslationActive": (False, "p_bool"),
        b"TranslationMin": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"TranslationMax": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"TranslationMinX": (False, "p_bool"),
        b"TranslationMinY": (False, "p_bool"),
        b"TranslationMinZ": (False, "p_bool"),
        b"TranslationMaxX": (False, "p_bool"),
        b"TranslationMaxY": (False, "p_bool"),
        b"TranslationMaxZ": (False, "p_bool"),
        b"RotationOrder": (0, "p_enum"),
        b"RotationSpaceForLimitOnly": (False, "p_bool"),
        b"RotationStiffnessX": (0.0, "p_number"),
        b"RotationStiffnessY": (0.0, "p_number"),
        b"RotationStiffnessZ": (0.0, "p_number"),
        b"AxisLen": (10.0, "p_number"),
        b"PreRotation": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"PostRotation": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"RotationActive": (False, "p_bool"),
        b"RotationMin": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"RotationMax": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"RotationMinX": (False, "p_bool"),
        b"RotationMinY": (False, "p_bool"),
        b"RotationMinZ": (False, "p_bool"),
        b"RotationMaxX": (False, "p_bool"),
        b"RotationMaxY": (False, "p_bool"),
        b"RotationMaxZ": (False, "p_bool"),
        b"InheritType": (0, "p_enum"),
        b"ScalingActive": (False, "p_bool"),
        b"ScalingMin": ((1.0, 1.0, 1.0), "p_vector_3d"),
        b"ScalingMax": ((1.0, 1.0, 1.0), "p_vector_3d"),
        b"ScalingMinX": (False, "p_bool"),
        b"ScalingMinY": (False, "p_bool"),
        b"ScalingMinZ": (False, "p_bool"),
        b"ScalingMaxX": (False, "p_bool"),
        b"ScalingMaxY": (False, "p_bool"),
        b"ScalingMaxZ": (False, "p_bool"),
        b"GeometricTranslation": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"GeometricRotation": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"GeometricScaling": ((1.0, 1.0, 1.0), "p_vector_3d"),
        b"MinDampRangeX": (0.0, "p_number"),
        b"MinDampRangeY": (0.0, "p_number"),
        b"MinDampRangeZ": (0.0, "p_number"),
        b"MaxDampRangeX": (0.0, "p_number"),
        b"MaxDampRangeY": (0.0, "p_number"),
        b"MaxDampRangeZ": (0.0, "p_number"),
        b"MinDampStrengthX": (0.0, "p_number"),
        b"MinDampStrengthY": (0.0, "p_number"),
        b"MinDampStrengthZ": (0.0, "p_number"),
        b"MaxDampStrengthX": (0.0, "p_number"),
        b"MaxDampStrengthY": (0.0, "p_number"),
        b"MaxDampStrengthZ": (0.0, "p_number"),
        b"PreferedAngleX": (0.0, "p_number"),
        b"PreferedAngleY": (0.0, "p_number"),
        b"PreferedAngleZ": (0.0, "p_number"),
        b"LookAtProperty": (None, "p_object"),
        b"UpVectorProperty": (None, "p_object"),
        b"Show": (True, "p_bool"),
        b"NegativePercentShapeSupport": (True, "p_bool"),
        b"DefaultAttributeIndex": (-1, "p_integer"),
        b"Freeze": (False, "p_bool"),
        b"LODBox": (False, "p_bool"),
        b"Lcl Translation": ((0.0, 0.0, 0.0), "p_lcl_translation"),
        b"Lcl Rotation": ((0.0, 0.0, 0.0), "p_lcl_rotation"),
        b"Lcl Scaling": ((1.0, 1.0, 1.0), "p_lcl_scaling"),
        b"Visibility": (1.0, "p_visibility"),
    }
    props.update(override_defaults)
    return FBXTemplate(b"Model", b"KFbxNode", props, nbr_users)


def fbx_template_def_nodeattribute_camera(override_defaults={}, nbr_users=0):
    props = override_defaults
    return FBXTemplate(b"NodeAttribute", b"KFbxCamera", props, nbr_users)


def fbx_template_def_nodeattribute_cameraswitcher(override_defaults={}, nbr_users=0):
    props = {
        b"Color": ((0.8, 0.8, 0.8), "p_color_rgb"),
        b"Camera Index": (1, "p_integer"),
    }
    props.update(override_defaults)
    return FBXTemplate(b"NodeAttribute", b"KFbxCameraSwitcher", props, nbr_users)


def fbx_template_def_nodeattribute_light(override_defaults={}, nbr_users=0):
    props = override_defaults
    return FBXTemplate(b"NodeAttribute", b"KFbxLight", props, nbr_users)


def fbx_template_def_geometry(override_defaults={}, nbr_users=0):
    props = {
        b"Color": ((0.8, 0.8, 0.8), "p_color_rgb"),
        b"BBoxMin": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"BBoxMax": ((0.0, 0.0, 0.0), "p_vector_3d"),
    }
    props.update(override_defaults)
    return FBXTemplate(b"Geometry", b"KFbxMesh", props, nbr_users)


def fbx_template_def_material(override_defaults={}, nbr_users=0):
    props = {
        b"ShadingModel": ("Lambert", "p_string"),
        b"MultiLayer": (False, "p_bool"),
        b"EmissiveColor": ((0.0, 0.0, 0.0), "p_color_rgb"),
        b"EmissiveFactor": (1.0, "p_number"),
        b"AmbientColor": ((0.2, 0.2, 0.2), "p_color_rgb"),
        b"AmbientFactor": (1.0, "p_number"),
        b"DiffuseColor": ((0.8, 0.8, 0.8), "p_color_rgb"),
        b"DiffuseFactor": (1.0, "p_number"),
        b"Bump": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"NormalMap": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"BumpFactor": (1.0, "p_number"),
        b"TransparentColor": ((0.0, 0.0, 0.0), "p_color_rgb"),
        b"TransparencyFactor": (0.0, "p_number"),
        b"DisplacementColor": ((0.0, 0.0, 0.0), "p_color_rgb"),
        b"DisplacementFactor": (1.0, "p_number"),
    }
    props.update(override_defaults)
    return FBXTemplate(b"Material", b"KFbxSurfaceLambert", props, nbr_users)


def fbx_template_def_pose(override_defaults={}, nbr_users=0):
    props = override_defaults  # No properties, by default.
    return FBXTemplate(b"Pose", b"", props, nbr_users)


##### Top-level FBX data container. #####

# Helper container gathering some data we need multiple times:
#     * templates.
#     * objects.
#     * connections.
#     * takes.
FBXData = namedtuple("FBXData", ("templates", "templates_users", "objects", "cameras", "meshes"))


def fbx_data_from_scene(scene, object_types):
    """
    Do some pre-processing over scene's data...
    """
    templates = {
        b"GlobalSettings": fbx_template_def_globalsettings(nbr_users=1),
    }

    # This is rather simple for now, maybe we could end generating templates with most-used values
    # instead of default ones?
    objects = {obj for obj in scene.objects if obj.type in object_types}
    cameras = {obj for obj in objects if obj.type == 'CAMERA'}
    meshes = {obj for obj in objects if obj.type == 'MESH'}

    if objects:
        # We use len(object) + len(camera) because of the CameraSwitcher objects...
        templates[b"Model"] = fbx_template_def_model(nbr_users=len(objects) + len(cameras))

    if cameras:
        nbr = len(cameras)
        templates[b"NodeAttribute::Camera"] = fbx_template_def_nodeattribute_camera(nbr_users=nbr)
        templates[b"NodeAttribute::CameraSwitcher"] = fbx_template_def_nodeattribute_cameraswitcher(nbr_users=nbr)

    if meshes:
        templates[b"Geometry"] = fbx_template_def_geometry(nbr_users=len(meshes))

    templates_users = sum(tmpl.nbr_users for tmpl in templates.values())
    return FBXData(templates, templates_users, objects, cameras, meshes)


##### Top-level FBX elements generators. #####

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
    elem_props_set(props, "p_integer", b"UpAxis", 1)
    elem_props_set(props, "p_integer", b"UpAxisSign", 1)
    elem_props_set(props, "p_integer", b"FrontAxis", 2)
    elem_props_set(props, "p_integer", b"FrontAxisSign", 1)
    elem_props_set(props, "p_integer", b"CoordAxis", 0)
    elem_props_set(props, "p_integer", b"CoordAxisSign", 1)
    elem_props_set(props, "p_number", b"UnitScaleFactor", 1.0)
    elem_props_set(props, "p_color_rgb", b"AmbientColor", (0.0, 0.0, 0.0))
    elem_props_set(props, "p_string", b"DefaultCamera", "")
    # XXX Those time stuff is taken from a file, have no (complete) idea what it means!
    elem_props_set(props, "p_enum", b"TimeMode", 11)
    elem_props_set(props, "p_timestamp", b"TimeSpanStart", 0)
    elem_props_set(props, "p_timestamp", b"TimeSpanStop", 479181389250)

    ##### End of GlobalSettings element.


def fbx_documents_elements(root, name=""):
    """
    Write 'Document' part of FBX root.
    Seems like FBX support multiple documents, but until I find examples of such, we'll stick to single doc!
    time is expected to be a datetime.datetime object, or None (using now() in this case).
    """
    ##### Start of Documents element.
    docs = elem_empty(root, b"Documents")

    elem_data_single_int32(docs, b"Count", 1)

    doc_uid = get_fbxuid_from_key("__FBX_Document__" + name)
    doc = elem_data_single_int64(docs, b"Document", doc_uid)
    doc.add_string(b"")
    doc.add_string_unicode(name)

    props = elem_properties(doc)
    elem_props_set(props, "p_object", b"SourceObject")
    elem_props_set(props, "p_string", b"ActiveAnimStackName", "")

    # XXX Probably some kind of offset? Binary one?
    #     Anyway, as long as we have only one doc, probably not an issue.
    elem_data_single_int64(doc, b"RootNode", 0)


def fbx_references_elements(root):
    """
    Have no idea what references are in FBX currently... Just writing empty element.
    """
    docs = elem_empty(root, b"References")


def fbx_definitions_elements(root, scene_data):
    """
    Templates definitions. Only used by Objects data afaik (apart from dummy GlobalSettings one).
    """
    definitions = elem_empty(root, b"Definitions")

    elem_data_single_int32(definitions, b"Version", FBX_TEMPLATES_VERSION)
    elem_data_single_int32(definitions, b"Count", scene_data.templates_users)

    for tmpl in scene_data.templates.values():
        fbx_template_generate(definitions, tmpl)


def fbx_objects_elements(root, scene_data):
    """
    Data (objects, geometry, material, textures, armatures, etc.
    """
    objects = elem_empty(root, b"Objects")

    for cam in scene_data.cameras:
        pass

    for mesh in scene_data.meshes:
        pass

    for obj in scene_data.objects:
        pass


def fbx_connections_elements(root, scene_data):
    """
    Relations between Objects (which material uses which texture, and so on).
    """
    connections = elem_empty(root, b"Connections")


def fbx_takes_elements(root, scene_data):
    """
    Animations. Have yet to check how this work...
    """
    takes = elem_empty(root, b"Takes")


##### "Main" functions. #####

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

    # XXX Temp, during dev...
    object_types = {'EMPTY', 'CAMERA', 'LAMP', 'MESH'}

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

    # Generate some data about exported scene...
    scene_data = fbx_data_from_scene(scene, object_types)

    root = elem_empty(None, b"")  # Root element has no id, as it is not saved per se!

    # Mostly FBXHeaderExtension and GlobalSettings.
    fbx_header_elements(root)

    # Documents and References are pretty much void currently.
    fbx_documents_elements(root, scene.name)
    fbx_references_elements(root)

    # Templates definitions.
    fbx_definitions_elements(root, scene_data)

    # Actual data.
    fbx_objects_elements(root, scene_data)

    # How data are inter-connected.
    fbx_connections_elements(root, scene_data)

    # Animation.
    fbx_takes_elements(root, scene_data)

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
