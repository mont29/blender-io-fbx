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


import array
import datetime
import math
import os
import time

import collections
from collections import namedtuple
import itertools
from itertools import zip_longest

import bpy
from mathutils import Vector, Matrix

from . import encode_bin, data_types


# "Constants"
FBX_VERSION = 7300
FBX_HEADER_VERSION = 1003
FBX_TEMPLATES_VERSION = 100

FBX_MODELS_VERSION = 232

FBX_GEOMETRY_VERSION = 124
FBX_GEOMETRY_NORMAL_VERSION = 101
FBX_GEOMETRY_SMOOTHING_VERSION = 102
FBX_GEOMETRY_VCOLOR_VERSION = 101
FBX_GEOMETRY_UV_VERSION = 101
FBX_GEOMETRY_MATERIAL_VERSION = 101
FBX_GEOMETRY_LAYER_VERSION = 100
FBX_MATERIAL_VERSION = 102
FBX_TEXTURE_VERSION = 202

FBX_NAME_CLASS_SEP = b"\x00\x01"


# Lamps.
FBX_LIGHT_TYPES = {
    'POINT': 0,  # Point.
    'SUN': 1,    # Directional.
    'SPOT': 2,   # Spot.
    'HEMI': 1,   # Directional.
    'AREA': 3,   # Area.
}
FBX_LIGHT_DECAY_TYPES = {
    'CONSTANT': 0,                   # None.
    'INVERSE_LINEAR': 1,             # Linear.
    'INVERSE_SQUARE': 2,             # Quadratic.
    'CUSTOM_CURVE': 2,               # Quadratic.
    'LINEAR_QUADRATIC_WEIGHTED': 2,  # Quadratic.
}


# Default global matrix.
MTX_GLOB = Matrix()
# Used for camera and lamp rotations.
MTX_X90 = Matrix.Rotation(math.pi / 2.0, 3, 'X')
# Used for mesh and armature rotations.
MTX4_Z90 = Matrix.Rotation(math.pi / 2.0, 4, 'Z')


##### Misc utilities #####

# Note: this could be in a utility (math.units e.g.)...

UNITS = {
    "meter": 1.0,  # Ref unit!
    "kilometer": 0.001,
    "millimeter": 1000.0,
    "foot": 1.0 / 0.3048,
    "inch": 1.0 / 0.0254,
    "turn": 1.0,  # Ref unit!
    "degree": 360.0,
    "radian": math.pi * 2.0,
}

def units_convert(val, u_from, u_to):
    """Convert value."""
    conv = UNITS[u_to] / UNITS[u_from]
    try:
        return (v * conv for v in val)
    except:
        return val * conv

##### UIDs code. #####

# ID class (mere int).
class UID(int):
    pass


# UIDs storage.
_keys_to_uids = {}
_uids_to_keys = {}


def _key_to_uid(uids, key):
    # TODO: Check this is robust enough for our needs!
    # Note: We assume we have already checked the related key wasn't yet in _keys_to_uids!
    #       As int64 is signed in FBX, we keep uids below 2**63...
    if isinstance(key, int) and 0 <= key < 2**63:
        # We can use value directly as id!
        uid = key
    else:
        uid = hash(key)
        if uid < 0:
            uid = -uid
        if uid >= 2**63:
            uid //= 2
    # Make sure our uid *is* unique.
    if uid in uids:
        inc = 1 if uid < 2**62 else -1
        while uid in uids:
            uid += inc
            if 0 > uid >= 2**63:
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
    return key, key + "_switcher", key + "_switcher_object"


def get_blender_material_key(mat):
    """Materials are actually (mat, tex) pairs."""
    return get_blenderID_key(mat[0]) + ";" + get_blenderID_key(mat[1])


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


def _elem_data_vec(elem, name, value, func_name):
    sub_elem = elem_empty(elem, name)
    func = getattr(sub_elem, func_name)
    for v in value:
        func(v)
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


def elem_data_vec_float64(elem, name, value):
    return _elem_data_vec(elem, name, value, "add_float64")

##### Generators for standard FBXProperties70 properties. #####

# Properties definitions, format: (b"type_1", b"type_2", b"type_3", "name_set_value_1", "name_set_value_2", ...)
# XXX Looks like there can be various variations of formats here... Will have to be checked ultimately!
#     Among other things, what are those "A"/"A+"/"AU" codes?
FBX_PROPERTIES_DEFINITIONS = {
    "p_bool": (b"bool", b"", b"", "add_int32"),  # Yes, int32 for a bool (and they do have a core bool type)!!!
    "p_integer": (b"int", b"Integer", b"", "add_int32"),
    "p_enum": (b"enum", b"", b"", "add_int32"),
    "p_number": (b"double", b"Number", b"", "add_float64"),
    "p_visibility": (b"Visibility", b"", b"A+", "add_float64"),
    "p_fov": (b"FieldOfView", b"", b"A+", "add_float64"),
    "p_fov_x": (b"FieldOfViewX", b"", b"A+", "add_float64"),
    "p_fov_y": (b"FieldOfViewY", b"", b"A+", "add_float64"),
    "p_vector_3d": (b"Vector3D", b"Vector", b"", "add_float64", "add_float64", "add_float64"),
    "p_lcl_translation": (b"Lcl Translation", b"", b"A+", "add_float64", "add_float64", "add_float64"),
    "p_lcl_rotation": (b"Lcl Rotation", b"", b"A+", "add_float64", "add_float64", "add_float64"),
    "p_lcl_scaling": (b"Lcl Scaling", b"", b"A+", "add_float64", "add_float64", "add_float64"),
    "p_color_rgb": (b"ColorRGB", b"Color", b"", "add_float64", "add_float64", "add_float64"),
    "p_string": (b"KString", b"", b"", "add_string_unicode"),
    "p_string_url": (b"KString", b"XRefUrl", b"", "add_string_unicode"),
    "p_timestamp": (b"KTime", b"Time", b"", "add_int64"),
    "p_object": (b"object", b"", b""),  # XXX Check this! No value for this prop???
}


def _elem_props_set(elem, ptype, name, value):
    p = elem_data_single_string(elem, b"P", name)
    for t in ptype[:3]:
        p.add_string(t)
    if len(ptype) == 4:
        getattr(p, ptype[3])(value)
    elif len(ptype) > 4:
        # We assume value is iterable, else it's a bug!
        for callback, val in zip(ptype[3:], value):
            getattr(p, callback)(val)


def elem_props_set(elem, ptype, name, value=None):
    ptype = FBX_PROPERTIES_DEFINITIONS[ptype]
    _elem_props_set(elem, ptype, name, value)


def elem_props_template_set(template, elem, ptype_name, name, value):
    """
    Only add a prop if the same value is not already defined in given template.
    Note it is important to not give iterators as value, here!
    """
    ptype = FBX_PROPERTIES_DEFINITIONS[ptype_name]
    tmpl_val, tmpl_ptype = template.properties.get(name, (None, None))
    if tmpl_ptype is not None:
        if ((len(ptype) == 4 and (tmpl_val, tmpl_ptype) == (value, ptype_name)) or
            (len(ptype) > 4 and (tuple(tmpl_val), tmpl_ptype) == (tuple(value), ptype_name))):
            return  # Already in template and same value.
    _elem_props_set(elem, ptype, name, value)


##### Generators for connection elements. #####

def elem_connection(elem, c_type, uid_src, uid_dst, prop_dst=None):
    e = elem_data_single_string(elem, b"C", c_type)
    e.add_int64(uid_src)
    e.add_int64(uid_dst)
    if prop_dst is not None:
        e.add_string(prop_dst)


def elem_connection_oo(elem, uid_src, uid_dst):
    """
    Object to Object connection.
    """
    elem_connection(elem, b"OO", uid_src, uid_dst)


def elem_connection_op(elem, uid_src, uid_dst, prop_dst):
    """
    Object to object Property connection.
    """
    elem_connection(elem, b"OP", uid_src, uid_dst, prop_dst)


##### Templates #####
# TODO: check all those "default" values, they should match Blender's default as much as possible, I guess?

FBXTemplate = namedtuple("FBXTemplate", ("type_name", "prop_type_name", "properties", "nbr_users"))


def fbx_template_generate(root, fbx_template):
    template = elem_data_single_string(root, b"ObjectType", fbx_template.type_name)
    elem_data_single_int32(template, b"Count", fbx_template.nbr_users)

    if fbx_template.properties:
        elem = elem_data_single_string(template, b"PropertyTemplate", fbx_template.prop_type_name)
        props = elem_properties(elem)
        for name, (value, ptype) in fbx_template.properties.items():
            elem_props_set(props, ptype, name, value)


def fbx_template_def_globalsettings(scene, settings, override_defaults=None, nbr_users=0):
    props = {}
    if override_defaults is not None:
        props.update(override_defaults)
    return FBXTemplate(b"GlobalSettings", b"", props, nbr_users)


def fbx_template_def_model(scene, settings, override_defaults=None, nbr_users=0):
    gscale = settings.global_scale
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
        b"RotationOrder": (0, "p_enum"),  # 'XYZ'
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
        b"ScalingMin": (Vector((1.0, 1.0, 1.0)) * gscale, "p_vector_3d"),
        b"ScalingMax": (Vector((1.0, 1.0, 1.0)) * gscale, "p_vector_3d"),
        b"ScalingMinX": (False, "p_bool"),
        b"ScalingMinY": (False, "p_bool"),
        b"ScalingMinZ": (False, "p_bool"),
        b"ScalingMaxX": (False, "p_bool"),
        b"ScalingMaxY": (False, "p_bool"),
        b"ScalingMaxZ": (False, "p_bool"),
        b"GeometricTranslation": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"GeometricRotation": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"GeometricScaling": (Vector((1.0, 1.0, 1.0)) * gscale, "p_vector_3d"),
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
        b"Lcl Scaling": (Vector((1.0, 1.0, 1.0)) * gscale, "p_lcl_scaling"),
        b"Visibility": (1.0, "p_visibility"),
    }
    if override_defaults is not None:
        props.update(override_defaults)
    return FBXTemplate(b"Model", b"KFbxNode", props, nbr_users)


def fbx_template_def_light(scene, settings, override_defaults=None, nbr_users=0):
    gscale = settings.global_scale
    props = {
        b"LightType": (0, "p_enum"),  # Point light.
        b"CastLight": (True, "p_bool"),
        b"Color": ((1.0, 1.0, 1.0), "p_color_rgb"),
        b"Intensity": (100.0, "p_number"),  # Times 100 compared to Blender values...
        b"DecayType": (2, "p_enum"),  # Quadratic.
        b"DecayStart": (30.0 * gscale, "p_number"),
        b"CastShadows": (True, "p_bool"),
        b"ShadowColor": ((0.0, 0.0, 0.0), "p_color_rgb"),
        b"AreaLightShape": (0, "p_enum"),  # Rectangle.
    }
    if override_defaults is not None:
        props.update(override_defaults)
    return FBXTemplate(b"NodeAttribute", b"KFbxLight", props, nbr_users)


def fbx_template_def_camera(scene, settings, override_defaults=None, nbr_users=0):
    props = {}
    if override_defaults is not None:
        props.update(override_defaults)
    return FBXTemplate(b"NodeAttribute", b"KFbxCamera", props, nbr_users)


def fbx_template_def_cameraswitcher(scene, settings, override_defaults=None, nbr_users=0):
    props = {
        b"Color": ((0.8, 0.8, 0.8), "p_color_rgb"),
        b"Camera Index": (1, "p_integer"),
    }
    if override_defaults is not None:
        props.update(override_defaults)
    return FBXTemplate(b"NodeAttribute", b"KFbxCameraSwitcher", props, nbr_users)


def fbx_template_def_geometry(scene, settings, override_defaults=None, nbr_users=0):
    props = {
        b"Color": ((0.8, 0.8, 0.8), "p_color_rgb"),
        b"BBoxMin": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"BBoxMax": ((0.0, 0.0, 0.0), "p_vector_3d"),
    }
    if override_defaults is not None:
        props.update(override_defaults)
    return FBXTemplate(b"Geometry", b"KFbxMesh", props, nbr_users)


def fbx_template_def_material(scene, settings, override_defaults=None, nbr_users=0):
    # WIP...
    props = {
        b"ShadingModel": ("phong", "p_string"),
        b"MultiLayer": (False, "p_bool"),
        # Lambert-specific.
        b"EmissiveColor": ((0.8, 0.8, 0.8), "p_color_rgb"),  # Same as diffuse.
        b"EmissiveFactor": (0.0, "p_number"),
        b"AmbientColor": ((0.0, 0.0, 0.0), "p_color_rgb"),
        b"AmbientFactor": (1.0, "p_number"),
        b"DiffuseColor": ((0.8, 0.8, 0.8), "p_color_rgb"),
        b"DiffuseFactor": (0.8, "p_number"),
        b"TransparentColor": ((0.8, 0.8, 0.8), "p_color_rgb"),  # Same as diffuse.
        b"TransparencyFactor": (0.0, "p_number"),
        b"NormalMap": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"Bump": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"BumpFactor": (1.0, "p_number"),
        b"DisplacementColor": ((0.0, 0.0, 0.0), "p_color_rgb"),
        b"DisplacementFactor": (0.0, "p_number"),
        # Phong-specific.
        b"SpecularColor": ((1.0, 1.0, 1.0), "p_color_rgb"),
        b"SpecularFactor": (0.5 / 2.0, "p_number"),
        # Not sure about that name,importer use this (but ShininessExponent for tex prop name!) :/
        b"Shininess": ((50.0 - 1.0) / 5.10, "p_number"),
        b"ReflectionColor": ((1.0, 1.0, 1.0), "p_color_rgb"),
        b"RefectionFactor": (0.0, "p_number"),
    }
    if override_defaults is not None:
        props.update(override_defaults)
    return FBXTemplate(b"Material", b"KFbxSurfacePhong", props, nbr_users)


def fbx_template_def_texture_file(scene, settings, override_defaults=None, nbr_users=0):
    # WIP...
    # XXX Not sure about all names!
    props = {
        b"TextureTypeUse": (0, "p_enum"),  # Standard.
        b"AlphaSource": (2, "p_enum"),  # Black (i.e. texture's alpha), XXX name guessed!.
        b"Texture alpha": (1.0, "p_number"),
        b"PremultiplyAlpha": (False, "p_bool"),
        b"CurrentTextureBlendMode": (0, "p_enum"),  # Translucent, assuming this means "Alpha over"!
        b"CurrentMappingType": (1, "p_enum"),  # Planar.
        b"WrapModeU": (0, "p_enum"),  # Repeat.
        b"WrapModeV": (0, "p_enum"),  # Repeat.
        b"UVSwap": (False, "p_bool"),
        b"Translation": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"Rotation": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"Scaling": ((1.0, 1.0, 1.0), "p_vector_3d"),
        b"TextureRotationPivot": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"TextureScalingPivot": ((0.0, 0.0, 0.0), "p_vector_3d"),
        # Not sure about those two... At least, UseMaterial should always be ON imho.
        b"UseMaterial": (True, "p_bool"),
        b"UseMipMap": (False, "p_bool"),
    }
    if override_defaults is not None:
        props.update(override_defaults)
    return FBXTemplate(b"Texture", b"KFbxFileTexture", props, nbr_users)


def fbx_template_def_video(scene, settings, override_defaults=None, nbr_users=0):
    # WIP...
    props = {
        # All pictures.
        b"Width": (0, "p_integer"),
        b"Height": (0, "p_integer"),
        b"Path": ("", "p_string_url"),
        b"AccessMode": (0, "p_enum"),  # Disk (0=Disk, 1=Mem, 2=DiskAsync).
        # All videos.
        b"StartFrame": (0, "p_integer"),
        b"StopFrame": (0, "p_integer"),
        b"Offset": (0, "p_timestamp"),
        b"PlaySpeed": (1.0, "p_number"),
        b"FreeRunning": (False, "p_bool"),
        b"Loop": (False, "p_bool"),
        b"InterlaceMode": (0, "p_enum"),  # None, i.e. progressive.
        # Image sequences.
        b"ImageSequence": (False, "p_bool"),
        b"ImageSequenceOffset": (0, "p_integer"),
        b"FrameRate": (scene.render.fps / scene.render.fps_base, "p_number"),
        b"LastFrame": (0, "p_integer"),
    }
    if override_defaults is not None:
        props.update(override_defaults)
    return FBXTemplate(b"Video", b"KFbxVideo", props, nbr_users)

 
def fbx_template_def_pose(gmat, gscale, override_defaults=None, nbr_users=0):
    props = {}
    if override_defaults is not None:
        props.update(override_defaults)
    return FBXTemplate(b"Pose", b"", props, nbr_users)


##### FBX objects generators. #####

def object_tx(ob, scene_data):
    """
    Generate object transform data (in parent space if parent exists and is exported, else in world space).
    Applies specific rotation to lamps and cameras (conversion Blender -> FBX).
    """
    matrix = ob.matrix_world

    if ob.parent and ob.parent in scene_data.objects:
        # We only want transform relative to parent if parent is also exported!
        matrix = ob.matrix_local
    else:
        # Only apply global transform (global space) to 'root' objects!
        matrix = scene_data.settings.global_matrix * matrix

    loc, rot, scale = matrix.decompose()
    matrix_rot = rot.to_matrix()

    # Lamps and camera need to be rotated.
    if ob.type == 'LAMP':
        matrix_rot = matrix_rot * Matrix.Rotation(math.pi / 2.0, 3, 'X')
    elif ob.type == 'CAMERA':
        matrix_rot = matrix_rot * Matrix.Rotation(math.pi / 2.0, 3, 'Y')

    rot = matrix_rot.to_euler()

    return loc, rot, scale, matrix, matrix_rot


def bone_tx(bone, scene_data):
    """
    Generate bone transform data (in parent space one if any, else in armature space).
    """
    matrix = bone.matrix_local * MTX4_Z90

    if bone.parent:
        par_matrix = bone.parent.matrix_local * MTX4_Z90
        matrix = par_matrix.inverted() * matrix

    loc, rot, scale = matrix.decompose()
    matrix_rot = rot.to_matrix()
    rot = rot.to_euler()  # quat -> euler

    return loc, rot, scale, matrix, matrix_rot


def fbx_name_class(name, cls):
    return FBX_NAME_CLASS_SEP.join((name, cls))


def fbx_data_lamp_elements(root, lamp, scene_data):
    """
    Write the Lamp data block.
    """
    gscale = scene_data.settings.global_scale
    gmat = scene_data.settings.global_matrix

    lamp_key = scene_data.data_lamps[lamp]
    do_light = True
    decay_type = FBX_LIGHT_DECAY_TYPES['CONSTANT']
    do_shadow = False
    shadow_color = Vector((0.0, 0.0, 0.0))
    if lamp.type not in {'HEMI'}:
        if lamp.type not in {'SUN'}:
            decay_type = FBX_LIGHT_DECAY_TYPES[lamp.falloff_type]
        do_light = (not lamp.use_only_shadow) and (lamp.use_specular or lamp.use_diffuse)
        do_shadow = lamp.shadow_method not in {'NOSHADOW'}
        shadow_color = lamp.shadow_color

    light = elem_data_single_int64(root, b"NodeAttribute", get_fbxuid_from_key(lamp_key))
    light.add_string(fbx_name_class(lamp.name.encode(), b"NodeAttribute"))
    light.add_string(b"Light")

    elem_data_single_int32(light, b"GeometryVersion", FBX_GEOMETRY_VERSION)  # Sic...

    tmpl = scene_data.templates[b"Light"]
    props = elem_properties(light)
    elem_props_template_set(tmpl, props, "p_enum", b"LightType", FBX_LIGHT_TYPES[lamp.type])
    elem_props_template_set(tmpl, props, "p_bool", b"CastLight", do_light)
    elem_props_template_set(tmpl, props, "p_color_rgb", b"Color", lamp.color)
    elem_props_template_set(tmpl, props, "p_number", b"Intensity", lamp.energy * 100.0)
    elem_props_template_set(tmpl, props, "p_enum", b"DecayType", decay_type)
    elem_props_template_set(tmpl, props, "p_number", b"DecayStart", lamp.distance * gscale)
    elem_props_template_set(tmpl, props, "p_bool", b"CastShadows", do_shadow)
    elem_props_template_set(tmpl, props, "p_color_rgb", b"ShadowColor", shadow_color)
    if lamp.type in {'SPOT'}:
        elem_props_template_set(tmpl, props, "p_number", b"OuterAngle", math.degrees(lamp.spot_size))
        elem_props_template_set(tmpl, props, "p_number", b"InnerAngle",
                                math.degrees(lamp.spot_size * (1.0 - lamp.spot_blend)))


def fbx_data_camera_elements(root, cam_obj, scene_data):
    """
    Write the Camera and CameraSwitcher data blocks.
    """
    gscale = scene_data.settings.global_scale
    gmat = scene_data.settings.global_matrix

    cam_data = cam_obj.data
    cam_key, cam_switcher_key, cam_switcher_object_key = scene_data.data_cameras[cam_obj]

    # Have no idea what are cam switchers...
    cam_switcher = elem_data_single_int64(root, b"NodeAttribute", get_fbxuid_from_key(cam_switcher_key))
    cam_switcher.add_string(fbx_name_class(cam_data.name.encode() + b"_switcher", b"NodeAttribute"))
    cam_switcher.add_string(b"CameraSwitcher")

    tmpl = scene_data.templates[b"CameraSwitcher"]
    props = elem_properties(cam_switcher)
    elem_props_template_set(tmpl, props, "p_integer", b"Camera Index", 100)

    elem_data_single_int32(cam_switcher, b"Version", 101)
    elem_data_single_string_unicode(cam_switcher, b"Name", cam_data.name + " switcher")
    elem_data_single_int32(cam_switcher, b"CameraID", 100)  # ???
    elem_data_single_int32(cam_switcher, b"CameraName", 100)  # ??? Integer???????
    elem_empty(cam_switcher, b"CameraIndexName")  # ???

    # Real data now, good old camera!
    # Object transform info.
    loc, rot, scale, matrix, matrix_rot = object_tx(cam_obj, scene_data)
    up = matrix_rot * Vector((0.0, 1.0, 0.0))
    to = matrix_rot * Vector((0.0, 0.0, -1.0))
    # Render settings.
    # TODO We could export much more...
    render = scene_data.scene.render
    width = render.resolution_x
    height = render.resolution_y
    aspect = width / height
    # Film width & height from mm to inches
    filmwidth = units_convert(cam_data.sensor_width, "millimeter", "inch")
    filmheight = units_convert(cam_data.sensor_height, "millimeter", "inch")
    filmaspect = filmwidth / filmheight
    # Film offset
    offsetx = filmwidth * cam_data.shift_x
    offsety = filmaspect * filmheight * cam_data.shift_y

    cam = elem_data_single_int64(root, b"NodeAttribute", get_fbxuid_from_key(cam_key))
    cam.add_string(fbx_name_class(cam_data.name.encode(), b"NodeAttribute"))
    cam.add_string(b"Camera")

    tmpl = scene_data.templates[b"Camera"]
    props = elem_properties(cam)
    elem_props_template_set(tmpl, props, "p_vector_3d", b"Position", loc)
    elem_props_template_set(tmpl, props, "p_vector_3d", b"UpVector", up)
    elem_props_template_set(tmpl, props, "p_vector_3d", b"InterestPosition", to)
    # Should we use world value?
    elem_props_template_set(tmpl, props, "p_color_rgb", b"BackgroundColor", (0.0, 0.0, 0.0))
    elem_props_template_set(tmpl, props, "p_bool", b"DisplayTurnTableIcon", True)

    elem_props_template_set(tmpl, props, "p_number", b"FilmWidth", filmwidth)
    elem_props_template_set(tmpl, props, "p_number", b"FilmHeight", filmheight)
    elem_props_template_set(tmpl, props, "p_number", b"FilmAspectRatio", filmaspect)
    elem_props_template_set(tmpl, props, "p_number", b"FilmOffsetX", offsetx)
    elem_props_template_set(tmpl, props, "p_number", b"FilmOffsetY", offsety)

    elem_props_template_set(tmpl, props, "p_enum", b"ApertureMode", 3)  # FocalLength.
    elem_props_template_set(tmpl, props, "p_enum", b"GateFit", 2)  # FitHorizontal.
    elem_props_template_set(tmpl, props, "p_fov", b"FieldOfView", math.degrees(cam_data.angle_x))
    elem_props_template_set(tmpl, props, "p_fov_x", b"FieldOfViewX", math.degrees(cam_data.angle_x))
    elem_props_template_set(tmpl, props, "p_fov_y", b"FieldOfViewY", math.degrees(cam_data.angle_y))
    # No need to convert to inches here...
    elem_props_template_set(tmpl, props, "p_number", b"FocalLength", cam_data.lens)
    elem_props_template_set(tmpl, props, "p_number", b"SafeAreaAspectRatio", aspect)

    elem_props_template_set(tmpl, props, "p_number", b"NearPlane", cam_data.clip_start * gscale)
    elem_props_template_set(tmpl, props, "p_number", b"FarPlane", cam_data.clip_end * gscale)
    elem_props_template_set(tmpl, props, "p_enum", b"BackPlaneDistanceMode", 1)  # RelativeToCamera.
    elem_props_template_set(tmpl, props, "p_number", b"BackPlaneDistance", cam_data.clip_end * gscale)

    elem_data_single_string(cam, b"TypeFlags", b"Camera")
    elem_data_single_int32(cam, b"GeometryVersion", 124)  # Sic...
    elem_data_vec_float64(cam, b"Position", loc)
    elem_data_vec_float64(cam, b"Up", up)
    elem_data_vec_float64(cam, b"LookAt", to)
    elem_data_single_int32(cam, b"ShowInfoOnMoving", 1)
    elem_data_single_int32(cam, b"ShowAudio", 0)
    elem_data_vec_float64(cam, b"AudioColor", (0.0, 1.0, 0.0))
    elem_data_single_float64(cam, b"CameraOrthoZoom", 1.0)


def fbx_data_mesh_elements(root, me, scene_data):
    """
    Write the Mesh (Geometry) data block.
    """
    # No gscale/gmat here, all data are supposed to be in object space.
    smooth_type = scene_data.settings.mesh_smooth_type

    me_key = scene_data.data_meshes[me]
    geom = elem_data_single_int64(root, b"Geometry", get_fbxuid_from_key(me_key))
    geom.add_string(fbx_name_class(me.name.encode(), b"Geometry"))
    geom.add_string(b"Mesh")

    elem_data_single_int32(geom, b"GeometryVersion", FBX_GEOMETRY_VERSION)

    # Vertex cos.
    t_co = array.array(data_types.ARRAY_FLOAT64, [0.0] * len(me.vertices) * 3)
    me.vertices.foreach_get("co", t_co)
    elem_data_single_float64_array(geom, b"Vertices", t_co)
    del t_co

    # Polygon indices.
    # A bit more complicated, as we have to ^-1 last index of each loop.
    t_vi = array.array(data_types.ARRAY_INT32, [0] * len(me.loops))
    me.loops.foreach_get("vertex_index", t_vi)
    t_ls = [None] * len(me.polygons)
    me.polygons.foreach_get("loop_start", t_ls)
    for ls in t_ls:
        t_vi[ls - 1] ^= -1
    elem_data_single_int32_array(geom, b"PolygonVertexIndex", t_vi)
    del t_vi
    del t_ls

    # TODO: edges.

    # And now, layers!

    # Loop normals.
    # NOTE: this is not supported by importer currently.
    def _nortuples_gen(raw_nors):
        return zip(*(iter(raw_nors),) * 3)

    me.calc_normals_split()
    t_ln = array.array(data_types.ARRAY_FLOAT64, [0.0] * len(me.loops) * 3)
    me.loops.foreach_get("normal", t_ln)
    lay_nor = elem_data_single_int32(geom, b"LayerElementNormal", 0)
    elem_data_single_int32(lay_nor, b"Version", FBX_GEOMETRY_NORMAL_VERSION)
    elem_data_single_string(lay_nor, b"Name", b"")
    elem_data_single_string(lay_nor, b"MappingInformationType", b"ByPolygonVertex")
    elem_data_single_string(lay_nor, b"ReferenceInformationType", b"IndexToDirect")

    ln2idx = tuple(set(_nortuples_gen(t_ln)))
    ln = array.array(data_types.ARRAY_FLOAT64, sum(ln2idx, ()))  # Flatten again...
    elem_data_single_float64_array(lay_nor, b"Normals", ln);
    del ln

    ln2idx = {nor: idx for idx, nor in enumerate(ln2idx)}
    li = array.array(data_types.ARRAY_INT32, (ln2idx[n] for n in _nortuples_gen(t_ln)))
    elem_data_single_int32_array(lay_nor, b"NormalIndex", li);
    del li

    del ln2idx
    del t_ln
    del _nortuples_gen
    me.free_normals_split()

    # TODO: binormal and tangent, to get a complete tspace export.

    # Smoothing.
    if smooth_type in {'FACE', 'EDGE'}:
        t_ps = None
        _map = b""
        if smooth_type == 'FACE':
            t_ps = array.array(data_types.ARRAY_INT32, [0] * len(me.polygons))
            me.polygons.foreach_get("use_smooth", t_ps)
            _map = b"ByPolygon"
        else:  # EDGE
            # Write Edge Smoothing
            # XXX Shouldn't this be also dependent on use_mesh_edges?
            t_ps = array.array(data_types.ARRAY_BOOL, [False] * len(me.edges))
            me.edges.foreach_get("use_edge_sharp", t_ps)
            t_ps = array.array(data_types.ARRAY_INT32, (not e for e in t_ps))
            _map = b"ByEdge"
        lay_smooth = elem_data_single_int32(geom, b"LayerElementSmoothing", 0)
        elem_data_single_int32(lay_smooth, b"Version", FBX_GEOMETRY_SMOOTHING_VERSION)
        elem_data_single_string(lay_smooth, b"Name", b"")
        elem_data_single_string(lay_smooth, b"MappingInformationType", _map)
        elem_data_single_string(lay_smooth, b"ReferenceInformationType", b"Direct")
        elem_data_single_int32_array(lay_smooth, b"Smoothing", t_ps);  # Sight, int32 for bool...
        del t_ps
        del _map

    # TODO: Edge crease (LayerElementCrease).

    # Write VertexColor Layers
    # note, no programs seem to use this info :/
    vcolnumber = len(me.vertex_colors)
    if vcolnumber:
        def _coltuples_gen(raw_cols):
            def _infinite_gen(val):
                while 1: yield val
            return zip(*(iter(raw_cols),) * 3 + (_infinite_gen(1.0),))  # We need a fake alpha...

        t_lc = array.array(data_types.ARRAY_FLOAT64, [0.0] * len(me.loops) * 3)
        for colindex, collayer in enumerate(me.vertex_colors):
            collayer.data.foreach_get("color", t_lc)
            lay_vcol = elem_data_single_int32(geom, b"LayerElementColor", colindex)
            elem_data_single_int32(lay_vcol, b"Version", FBX_GEOMETRY_VCOLOR_VERSION)
            elem_data_single_string_unicode(lay_vcol, b"Name", collayer.name)
            elem_data_single_string(lay_vcol, b"MappingInformationType", b"ByPolygonVertex")
            elem_data_single_string(lay_vcol, b"ReferenceInformationType", b"IndexToDirect")

            col2idx = tuple(set(_coltuples_gen(t_lc)))
            lc = array.array(data_types.ARRAY_FLOAT64, sum(col2idx, ()))  # Flatten again...
            elem_data_single_float64_array(lay_vcol, b"Colors", lc);
            del lc

            col2idx = {col: idx for idx, col in enumerate(col2idx)}
            li = array.array(data_types.ARRAY_INT32, (col2idx[c] for c in _coltuples_gen(t_lc)))
            elem_data_single_int32_array(lay_vcol, b"ColorIndex", li);
            del li
            del col2idx
        del t_lc
        del _coltuples_gen

    # Write UV layers.
    # Note: LayerElementTexture is deprecated since FBX 2011 - luckily!
    #       Textures are now only related to materials, in FBX!
    uvnumber = len(me.uv_layers)
    if uvnumber:
        def _uvtuples_gen(raw_uvs):
            return zip(*(iter(raw_uvs),) * 2)

        t_luv = array.array(data_types.ARRAY_FLOAT64, [0.0] * len(me.loops) * 2)
        for uvindex, uvlayer in enumerate(me.uv_layers):
            uvlayer.data.foreach_get("uv", t_luv)
            lay_uv = elem_data_single_int32(geom, b"LayerElementUV", uvindex)
            elem_data_single_int32(lay_uv, b"Version", FBX_GEOMETRY_UV_VERSION)
            elem_data_single_string_unicode(lay_uv, b"Name", uvlayer.name)
            elem_data_single_string(lay_uv, b"MappingInformationType", b"ByPolygonVertex")
            elem_data_single_string(lay_uv, b"ReferenceInformationType", b"IndexToDirect")

            uv2idx = tuple(set(_uvtuples_gen(t_luv)))
            luv = array.array(data_types.ARRAY_FLOAT64, sum(uv2idx, ()))  # Flatten again...
            elem_data_single_float64_array(lay_uv, b"UV", luv);
            del luv

            uv2idx = {uv: idx for idx, uv in enumerate(uv2idx)}
            li = array.array(data_types.ARRAY_INT32, (uv2idx[uv] for uv in _uvtuples_gen(t_luv)))
            elem_data_single_int32_array(lay_uv, b"UVIndex", li);
            del li
            del uv2idx
        del t_luv
        del _uvtuples_gen

    # TODO: materials.

    layer = elem_data_single_int32(geom, b"Layer", 0)
    elem_data_single_int32(layer, b"Version", FBX_GEOMETRY_LAYER_VERSION)
    lay_nor = elem_empty(layer, b"LayerElement")
    elem_data_single_string(lay_nor, b"Type", b"LayerElementNormal")
    elem_data_single_int32(lay_nor, b"TypeIndex", 0)
    if smooth_type in {'FACE', 'EDGE'}:
        lay_smooth = elem_empty(layer, b"LayerElement")
        elem_data_single_string(lay_smooth, b"Type", b"LayerElementSmoothing")
        elem_data_single_int32(lay_smooth, b"TypeIndex", 0)
    if vcolnumber:
        lay_vcol = elem_empty(layer, b"LayerElement")
        elem_data_single_string(lay_vcol, b"Type", b"LayerElementColor")
        elem_data_single_int32(lay_vcol, b"TypeIndex", 0)
    if uvnumber:
        lay_uv = elem_empty(layer, b"LayerElement")
        elem_data_single_string(lay_uv, b"Type", b"LayerElementUV")
        elem_data_single_int32(lay_uv, b"TypeIndex", 0)

    # Add other uv and/or vcol layers...
    for vcolidx, uvidx in zip_longest(range(1, vcolnumber), range(1, uvnumber), fillvalue=0):
        layer = elem_data_single_int32(geom, b"Layer", max(vcolidx, uvidx))
        elem_data_single_int32(layer, b"Version", FBX_GEOMETRY_LAYER_VERSION)
        if vcolidx:
            lay_vcol = elem_empty(layer, b"LayerElement")
            elem_data_single_string(lay_vcol, b"Type", b"LayerElementColor")
            elem_data_single_int32(lay_vcol, b"TypeIndex", vcolidx)
        if uvidx:
            lay_uv = elem_empty(layer, b"LayerElement")
            elem_data_single_string(lay_uv, b"Type", b"LayerElementUV")
            elem_data_single_int32(lay_uv, b"TypeIndex", uvidx)


def fbx_data_material_elements(root, mat, scene_data):
    """
    Write the Material data block.
    """
    world = next(iter(scene_data.world.keys()))

    mat_key = scene_data.data_materials[mat]
    # Approximation...
    mat_type = b"phong" if mat.specular_shader in {'COOKTORR', 'PHONG', 'BLINN'} else b"lambert"

    fbx_mat = elem_data_single_int64(root, b"Material", get_fbxuid_from_key(mat_key))
    fbx_mat.add_string(fbx_name_class(mat.name.encode(), b"Material"))
    fbx_mat.add_string(b"")

    elem_data_single_int32(fbx_mat, b"Version", FBX_MATERIAL_VERSION)
    # those are not yet properties, it seems...
    elem_data_single_string(fbx_mat, b"ShadingModel", mat_type)
    elem_data_single_int32(fbx_mat, b"MultiLayer", 0)  # Should be bool...

    tmpl = scene_data.templates[b"Material"]
    props = elem_properties(fbx_mat)
    elem_props_template_set(tmpl, props, "p_color_rgb", b"EmissiveColor", mat.diffuse_color)
    elem_props_template_set(tmpl, props, "p_number", b"EmissiveFactor", mat.emit)
    elem_props_template_set(tmpl, props, "p_color_rgb", b"AmbientColor", world.ambient_color)
    elem_props_template_set(tmpl, props, "p_number", b"AmbientFactor", mat.ambient)
    elem_props_template_set(tmpl, props, "p_color_rgb", b"DiffuseColor", mat.diffuse_color)
    elem_props_template_set(tmpl, props, "p_number", b"DiffuseFactor", mat.diffuse_intensity)
    elem_props_template_set(tmpl, props, "p_color_rgb", b"TransparentColor", mat.diffuse_color)
    elem_props_template_set(tmpl, props, "p_number", b"TransparencyFactor", mat.alpha if mat.use_transparency else 1.0)
    # Those are for later!
    """ 
    b"NormalMap": ((0.0, 0.0, 0.0), "p_vector_3d"),
    b"Bump": ((0.0, 0.0, 0.0), "p_vector_3d"),
    b"BumpFactor": (1.0, "p_number"),
    b"DisplacementColor": ((0.0, 0.0, 0.0), "p_color_rgb"),
    b"DisplacementFactor": (0.0, "p_number"),
    """
    if mat_type == b"phong":
        elem_props_template_set(tmpl, props, "p_color_rgb", b"SpecularColor", mat.specular_color)
        elem_props_template_set(tmpl, props, "p_number", b"SpecularFactor", mat.specular_intensity / 2.0)
        elem_props_template_set(tmpl, props, "p_number", b"Shininess", (mat.specular_hardness - 1.0) / 5.10)
        elem_props_template_set(tmpl, props, "p_color_rgb", b"ReflectionColor", mat.mirror_color)
        elem_props_template_set(tmpl, props, "p_number", b"RefectionFactor",
                                mat.raytrace_mirror.reflect_factor if mat.raytrace_mirror.use else 0.0)


def _gen_vid_path(img, scene_data):
    msetts = scene_data.settings.media_settings
    fname_rel = bpy_extras.io_utils.path_reference(img.filepath, msetts.base_src, msetts.base_dst, msetts.path_mode,
                                                   msetts.subdir, msetts.copy_set, img.library)
    fname_strip = bpy.path.basename(fname_rel)

    if scene_data.settings.embed_textures:

def fbx_data_texture_file_elements(root, tex, scene_data):
    """
    Write the (file) Texture data block.
    """
    # XXX All this is very fuzzy to me currently...
    #     Textures do not seem to use properties as much as they could.
    #     And I found even in 7.4 files VideoTexture used for mere png's... :/
    #     For now assuming most logical and simple stuff.

    tex_key = scene_data.data_textures[tex]
    img = tex.texture.image

    fbx_tex = elem_data_single_int64(root, b"Texture", get_fbxuid_from_key(tex_key))
    fbx_tex.add_string(fbx_name_class(tex.name.encode(), b"Texture"))
    fbx_tex.add_string(b"")

    elem_data_single_string(fbx_tex, b"Type", b"TextureVideoClip")
    elem_data_single_int32(fbx_tex, b"Version", FBX_TEXTURE_VERSION)
    elem_data_single_string(fbx_tex, b"TextureName", fbx_name_class(tex.name.encode(), b"Texture"))
    elem_data_single_string(fbx_tex, b"Media", fbx_name_class(tex.name.encode(), b"Texture"))
    elem_data_single_string(fbx_tex, b"TextureName", fbx_name_class(tex.name.encode(), b"Texture"))
    elem_data_single_string(fbx_tex, b"TextureName", fbx_name_class(tex.name.encode(), b"Texture"))

            ["Properties70", [], "", [
                ["P", ["UseMaterial", "bool", "", "", 1], "SSSSI", []]]],
            ["", ["HDR::Video"], "S", []],
            ["FileName", ["E:/HyperspaceMadness_UE3/SpaceMadness/Art/demos/DX11_Examples/Minion_LOD2_DX11_1024_Animation_Ram.fbm/Global_Illumination.png"], "S", []],
            ["RelativeFilename", ["Minion_LOD2_DX11_1024_Animation_Ram.fbm\\Global_Illumination.png"], "S", []],

    tmpl = scene_data.templates[b"TextureFile"]
    props = elem_properties(fbx_tex)
    elem_props_template_set(tmpl, props, "p_enum", b"LightType", FBX_LIGHT_TYPES[lamp.type])
    elem_props_template_set(tmpl, props, "p_bool", b"CastLight", do_light)
    elem_props_template_set(tmpl, props, "p_color_rgb", b"Color", lamp.color)
    elem_props_template_set(tmpl, props, "p_number", b"Intensity", lamp.energy * 100.0)
    elem_props_template_set(tmpl, props, "p_enum", b"DecayType", decay_type)
    elem_props_template_set(tmpl, props, "p_number", b"DecayStart", lamp.distance * gscale)
    elem_props_template_set(tmpl, props, "p_bool", b"CastShadows", do_shadow)
    elem_props_template_set(tmpl, props, "p_color_rgb", b"ShadowColor", shadow_color)
    if lamp.type in {'SPOT'}:
        elem_props_template_set(tmpl, props, "p_number", b"OuterAngle", math.degrees(lamp.spot_size))
        elem_props_template_set(tmpl, props, "p_number", b"InnerAngle",
                                math.degrees(lamp.spot_size * (1.0 - lamp.spot_blend)))


        b"TextureTypeUse": (0, "p_enum"),  # Standard.
        b"AlphaSource": (2, "p_enum"),  # Black (i.e. texture's alpha), XXX name guessed!.
        b"Alpha": (1.0, "p_number"),
        b"PremultiplyAlpha": (False, "p_bool"),
        b"CurrentTextureBlendMode": (0, "p_enum"),  # Translucent, assuming this means "Alpha over"!
        b"CurrentMappingType": (1, "p_enum"),  # Planar.
        b"WrapModeU": (0, "p_enum"),  # Repeat.
        b"WrapModeV": (0, "p_enum"),  # Repeat.
        b"UVSwap": (False, "p_bool"),
        b"Translation": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"Rotation": ((0.0, 0.0, 0.0), "p_vector_3d"),
        b"Scaling": ((1.0, 1.0, 1.0), "p_vector_3d"),
        b"RotationPivot": ((0.0, 0.0, 0.0), "p_vector_3d"),  # Assuming (0.0, 0.0, 0.0) is the center of picture...
        b"ScalingPivot": ((0.0, 0.0, 0.0), "p_vector_3d"),  # Assuming (0.0, 0.0, 0.0) is the center of picture...


        ["Texture", [984120400, "HDR::Texture", ""], "LSS", [
            ["Type", ["TextureVideoClip"], "S", []],
            ["Version", [202], "I", []],
            ["TextureName", ["HDR::Texture"], "S", []],
            ["Properties70", [], "", [
                ["P", ["UseMaterial", "bool", "", "", 1], "SSSSI", []]]],
            ["Media", ["HDR::Video"], "S", []],
            ["FileName", ["E:/HyperspaceMadness_UE3/SpaceMadness/Art/demos/DX11_Examples/Minion_LOD2_DX11_1024_Animation_Ram.fbm/Global_Illumination.png"], "S", []],
            ["RelativeFilename", ["Minion_LOD2_DX11_1024_Animation_Ram.fbm\\Global_Illumination.png"], "S", []],
            ["ModelUVTranslation", [0.0, 0.0], "DD", []],
            ["ModelUVScaling", [1.0, 1.0], "DD", []],
            ["Texture_Alpha_Source", ["None"], "S", []],
            ["Cropping", [0, 0, 0, 0], "IIII", []]]],

 
def fbx_data_video_elements(root, vid, scene_data):
    """
    Write the actual image data block.
    """
    # TODO: this can embed the actual image/video data!

        ["Video", [1172616112, "SuitA_Normal1::Video", "Clip"], "LSS", [
            ["Type", ["Clip"], "S", []],
            ["Properties70", [], "", [
                ["P", ["Path", "KString", "XRefUrl", "", "E:/HyperspaceMadness_UE3/SpaceMadness/Art/demos/DX11_Examples/Minion_LOD2_DX11_1024_Animation_Ram.fbm/MinionSuitA_Normal.png"], "SSSSS", []]]],
            ["UseMipMap", [0], "I", []],
            ["Filename", ["E:/HyperspaceMadness_UE3/SpaceMadness/Art/demos/DX11_Examples/Minion_LOD2_DX11_1024_Animation_Ram.fbm/MinionSuitA_Normal.png"], "S", []],
            ["RelativeFilename", ["Minion_LOD2_DX11_1024_Animation_Ram.fbm\\MinionSuitA_Normal.png"], "S", []],
            ["Content", ["<byte_array>"]]]]


def fbx_data_object_elements(root, obj, scene_data):
    """
    Write the Object (Model) data blocks.
    """
    gscale = scene_data.settings.global_scale
    gmat = scene_data.settings.global_matrix

    obj_type = b"Null"  # default, sort of empty...
    if (obj.type == 'MESH'):
        obj_type = b"Mesh"
    elif (obj.type == 'LAMP'):
        obj_type = b"Light"
    elif (obj.type == 'CAMERA'):
        obj_type = b"Camera"
    obj_key = scene_data.objects[obj]
    model = elem_data_single_int64(root, b"Model", get_fbxuid_from_key(obj_key))
    model.add_string(fbx_name_class(obj.name.encode(), b"Model"))
    model.add_string(obj_type)

    elem_data_single_int32(model, b"Version", FBX_MODELS_VERSION)

    # Object transform info.
    loc, rot, scale, matrix, matrix_rot = object_tx(obj, scene_data)
    rot = tuple(units_convert(rot, "radian", "degree"))

    tmpl = scene_data.templates[b"Model"]
    # For now add only loc/rot/scale...
    props = elem_properties(model)
    elem_props_template_set(tmpl, props, "p_lcl_translation", b"Lcl Translation", loc)
    elem_props_template_set(tmpl, props, "p_lcl_rotation", b"Lcl Rotation", rot)
    elem_props_template_set(tmpl, props, "p_lcl_scaling", b"Lcl Scaling", scale)

    # Those settings would obviously need to be edited in a complete version of the exporter, may depends on
    # object type, etc.
    elem_data_single_int32(model, b"MultiLayer", 0)
    elem_data_single_int32(model, b"MultiTake", 0)
    elem_data_single_bool(model, b"Shading", True)
    elem_data_single_string(model, b"Culling", b"CullingOff")

    if obj.type == 'CAMERA':
        # Why, oh why are FBX cameras such a mess???
        # And WHY add camera data HERE??? Not even sure this is needed...
        render = scene_data.scene.render
        width = render.resolution_x * 1.0
        height = render.resolution_y * 1.0
        elem_props_template_set(tmpl, props, "p_enum", b"ResolutionMode", 0)  # Don't know what it means
        elem_props_template_set(tmpl, props, "p_number", b"AspectW", width)
        elem_props_template_set(tmpl, props, "p_number", b"AspectH", height)
        elem_props_template_set(tmpl, props, "p_bool", b"ViewFrustum", True)
        elem_props_template_set(tmpl, props, "p_enum", b"BackgroundMode", 0)  # Don't know what it means
        elem_props_template_set(tmpl, props, "p_bool", b"ForegroundTransparent", True)

        # And - houra! - we also have to add a fake object for the cam switcher.
        _1, _2, obj_cam_switcher_key = scene_data.data_cameras[obj]
        cam_switcher_model = elem_data_single_int64(root, b"Model", get_fbxuid_from_key(obj_cam_switcher_key))
        cam_switcher_model.add_string(fbx_name_class(obj.name.encode() + b"_switcher", b"Model"))
        cam_switcher_model.add_string(b"CameraSwitcher")

        elem_data_single_int32(cam_switcher_model, b"Version", FBX_MODELS_VERSION)

        elem_properties(cam_switcher_model)
        # Nothing to add (loc/rot/scale has no importance here).

        elem_data_single_int32(cam_switcher_model, b"MultiLayer", 0)
        elem_data_single_int32(cam_switcher_model, b"MultiTake", 1)
        elem_data_single_bool(cam_switcher_model, b"Shading", True)
        elem_data_single_string(cam_switcher_model, b"Culling", b"CullingOff")


##### Top-level FBX data container. #####

# Helper container gathering some data we need multiple times:
#     * templates.
#     * objects.
#     * connections.
#     * takes.
FBXData = namedtuple("FBXData", (
    "templates", "templates_users",
    "settings", "scene", "objects",
    "data_lamps", "data_cameras", "data_meshes",
    "data_world", "data_materials", "data_textures", "data_videos",
))


def fbx_mat_properties_from_texture(tex):
    """
    Returns a set of FBX metarial properties that are affected by the given texture.
    Quite obviously, this is a fuzzy and far-from-perfect mapping! Amounts of influence are completely lost, e.g.
    Note tex is actually expected to be a texture slot.
    """
    # Tex influence does not exists in FBX, so assume influence < 0.5 = no influence... :/
    INLUENCE_THRESHOLD = 0.5

    tex_fbx_props = set()
    # mat is assumed to be Lambert diffuse...
    if tex.use_map_diffuse and tex.diffuse_factor >= INLUENCE_THRESHOLD:
        tex_fbx_props.add(b"DiffuseFactor")
    if tex.use_map_color_diffuse and tex.diffuse_color_factor >= INLUENCE_THRESHOLD:
        tex_fbx_props.add(b"Diffuse")
    if tex.use_map_alpha and tex.alpha_factor >= INLUENCE_THRESHOLD:
        tex_fbx_props.add(b"TransparencyFactor")
    # etc., will complete the list later.

    return tex_fbx_props


def fbx_data_from_scene(scene, settings):
    """
    Do some pre-processing over scene's data...
    """
    objtypes = settings.object_types

    templates = {
        b"GlobalSettings": fbx_template_def_globalsettings(scene, settings, nbr_users=1),
    }

    # This is rather simple for now, maybe we could end generating templates with most-used values
    # instead of default ones?
    objects = {obj: get_blenderID_key(obj) for obj in scene.objects if obj.type in objtypes}
    data_lamps = {obj.data: get_blenderID_key(obj.data) for obj in objects if obj.type == 'LAMP'}
    # Unfortunately, FBX camera data contains object-level data (like position, orientation, etc.)...
    data_cameras = {obj: get_blender_camera_keys(obj.data) for obj in objects if obj.type == 'CAMERA'}
    data_meshes = {obj.data: get_blenderID_key(obj.data) for obj in objects if obj.type == 'MESH'}

    # Some world settings are embedded in FBX materials...
    data_world = {scene.world: get_blenderID_key(scene.world)}

    data_materials = {}
    for obj in objects:
        for mat_s in obj.material_slots:
            mat = mat_s.material
            # Note theoretically, FBX supports any kind of materials, even GLSL shaders etc.
            # However, I doubt anything else than Lambert/Phong is really portable!
            # TODO: Support nodes (*BIG* todo!).
            if mat.type in {'SURFACE'} and mat.diffuse_shader in {'LAMBERT'} and not mat.use_nodes:
                if mat in data_materials:
                    data_materials[mat][1].append(obj)
                else:
                    data_materials[mat] = (get_blenderID_key(mat), [obj])

    # Note FBX textures also holds their mapping info.
    data_textures = {}
    # FbxVideo also used to store static images...
    data_videos = {}
    # For now, do not use world textures, don't think they can be linked to anything FBX wise...
    for mat in data_materials.keys():
        for tex in material.texture_slots:
            # For now, only consider image textures.
            # Note FBX does has support for procedural, but this is not portable at all (opaque blob),
            # so not useful for us.
            # TODO I think ENVIRONMENT_MAP should be usable in FBX as well, but for now let it aside.
            #if tex.texture.type not in {'IMAGE', 'ENVIRONMENT_MAP'}:
            if tex.texture.type not in {'IMAGE'}:
                continue
            img = tex.texture.image
            if img is None:
                continue
            # Find out whether we can actually use this texture for this material, in FBX context.
            tex_fbx_props = fbx_mat_properties_from_texture(tex)
            if not tex_fbx_props:
                continue
            if tex in data_textures:
                data_textures[tex][1][mat] = tex_fbx_props
            else:
                data_textures[tex] = (get_blenderID_key(tex.name), {mat: tex_fbx_props})
            if img in data_videos:
                data_videos[img][1].append(tex)
            else:
                data_videos[img] = (get_blenderID_key(img.name), [tex])

    if objects:
        # We use len(object) + len(data_cameras) because of the CameraSwitcher objects...
        templates[b"Model"] = fbx_template_def_model(scene, settings, nbr_users=len(objects) + len(data_cameras))

    if data_lamps:
        templates[b"Light"] = fbx_template_def_light(scene, settings, nbr_users=len(data_lamps))

    if data_cameras:
        nbr = len(data_cameras)
        templates[b"Camera"] = fbx_template_def_camera(scene, settings, nbr_users=nbr)
        templates[b"CameraSwitcher"] = fbx_template_def_cameraswitcher(scene, settings, nbr_users=nbr)

    if data_meshes:
        templates[b"Geometry"] = fbx_template_def_geometry(scene, settings, nbr_users=len(data_meshes))

    # No world support in FBX...
    """
    if data_world:
        templates[b"World"] = fbx_template_def_world(scene, settings, nbr_users=len(data_world))
    """

    if data_materials:
        templates[b"Material"] = fbx_template_def_material(scene, settings, nbr_users=len(data_materials))

    if data_textures:
        templates[b"TextureFile"] = fbx_template_def_texture_file(scene, settings, nbr_users=len(data_textures))

    if data_videos:
        templates[b"Video"] = fbx_template_def_video(scene, settings, nbr_users=len(data_videos))

    templates_users = sum(tmpl.nbr_users for tmpl in templates.values())
    return FBXData(
        templates, templates_users,
        settings, scene, objects,
        data_lamps, data_cameras, data_meshes,
        data_world, data_materials, data_textures, data_videos,
    )


##### Top-level FBX elements generators. #####

def fbx_header_elements(root, scene_data, time=None):
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


def fbx_documents_elements(root, scene_data):
    """
    Write 'Document' part of FBX root.
    Seems like FBX support multiple documents, but until I find examples of such, we'll stick to single doc!
    time is expected to be a datetime.datetime object, or None (using now() in this case).
    """
    name = scene_data.scene.name

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


def fbx_references_elements(root, scene_data):
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

    for lamp in scene_data.data_lamps.keys():
        fbx_data_lamp_elements(objects, lamp, scene_data)

    for cam in scene_data.data_cameras.keys():
        fbx_data_camera_elements(objects, cam, scene_data)

    for mesh in scene_data.data_meshes:
        fbx_data_mesh_elements(objects, mesh, scene_data)

    for obj in scene_data.objects.keys():
        fbx_data_object_elements(objects, obj, scene_data)

    for mat in scene_data.data_materials.keys():
        fbx_data_material_elements(objects, mat, scene_data)

    for tex in scene_data.data_textures.keys():
        fbx_data_texture_file_elements(objects, tex, scene_data)

    for vid in scene_data.data_videos.keys():
        fbx_data_video_elements(objects, vid, scene_data)


def fbx_connections_elements(root, scene_data):
    """
    Relations between Objects (which material uses which texture, and so on).
    """
    connections = elem_empty(root, b"Connections")

    for obj, obj_key in scene_data.objects.items():
        par = obj.parent
        par_key = 0
        if par and par in scene_data.objects:
            # TODO: Check this is the correct way to have object parenting!
            par_key = scene_data.objects[par]
        elem_connection_oo(connections, get_fbxuid_from_key(obj_key), get_fbxuid_from_key(par_key))

    # And now, object data.
    for obj_cam, (cam_key, cam_switcher_key, cam_obj_switcher_key) in scene_data.data_cameras.items():
        # Looks like the 'object' ('Model' in FBX) for the camera switcher is not linked to anything in FBX...
        elem_connection_oo(connections, get_fbxuid_from_key(cam_switcher_key),
                        get_fbxuid_from_key(cam_obj_switcher_key))
        cam_obj_key = scene_data.objects[obj_cam]
        elem_connection_oo(connections, get_fbxuid_from_key(cam_key), get_fbxuid_from_key(cam_obj_key))

    for obj, obj_key in scene_data.objects.items():
        if obj.type == 'LAMP':
            lamp_key = scene_data.data_lamps[obj.data]
            elem_connection_oo(connections, get_fbxuid_from_key(lamp_key), get_fbxuid_from_key(obj_key))
        elif obj.type == 'MESH':
            mesh_key = scene_data.data_meshes[obj.data]
            elem_connection_oo(connections, get_fbxuid_from_key(mesh_key), get_fbxuid_from_key(obj_key))

    for mat, (mat_key, objs) in scene_data.data_materials.items():
        for obj in objs:
            obj_key = scene_data.data_objects[obj]
            elem_connection_oo(connections, get_fbxuid_from_key(mat_key), get_fbxuid_from_key(obj_key))

    for tex, (tex_key, mats) in scene_data.data_textures.items():
        for mat, fbx_mat_props in mats.items():
            mat_key = scene_data.data_materials[mat]
            for fbx_prop in fbx_mat_props:
                elem_connection_op(connections, get_fbxuid_from_key(tex_key), get_fbxuid_from_key(mat_key), fbx_prop)

    for vid, (vid_key, texs) in scene_data.data_videos.items():
        for tex in texs:
            tex_key = scene_data.data_textures[tex]
            elem_connection_oo(connections, get_fbxuid_from_key(vid_key), get_fbxuid_from_key(tex_key))


def fbx_takes_elements(root, scene_data):
    """
    Animations. Have yet to check how this work...
    """
    takes = elem_empty(root, b"Takes")


##### "Main" functions. #####
FBXSettingsMedia = namedtuple("FBXSettingsMedia", (
    "path_mode", "base_src", "base_dst", "subdir",
    "embed_textures", "copy_set",
))
FBXSettings = namedtuple("FBXSettings", (
    "global_matrix", "global_scale", "context_objects", "object_types", "use_mesh_modifiers",
    "mesh_smooth_type", "use_mesh_edges", "use_armature_deform_only",
    "use_anim", "use_anim_optimize", "anim_optimize_precision", "use_anim_action_all", "use_default_take",
    "use_metadata", "media_settings",
))

# This func can be called with just the filepath
def save_single(operator, scene, filepath="",
                global_matrix=MTX_GLOB,
                context_objects=None,
                object_types=None,
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
                embed_textures=False,
                **kwargs
                ):

    if object_types is None:
        # XXX Temp, during dev...
        object_types = {'EMPTY', 'CAMERA', 'LAMP', 'MESH'}
        #object_types = {'EMPTY', 'CAMERA', 'LAMP', 'ARMATURE', 'MESH'}

    global_scale = global_matrix.median_scale

    media_settings = FBXSettingsMedia(
        path_mode,
        os.path.dirname(bpy.data.filepath),  # base_src
        os.path.dirname(filepath),  # base_dst
        os.path.basename(filepath) + ".fbm",  # subdir, local dir where to put images (medias), using FBX conventions.
        embed_textures,
        set(),  # copy_set
    )

    settings = FBXSettings(
        global_matrix, global_scale, context_objects, object_types, use_mesh_modifiers,
        mesh_smooth_type, use_mesh_edges, use_armature_deform_only,
        use_anim, use_anim_optimize, anim_optimize_precision, use_anim_action_all, use_default_take,
        use_metadata, media_settings,
    )

    import bpy_extras.io_utils

    print('\nFBX export starting... %r' % filepath)
    start_time = time.process_time()

    # Generate some data about exported scene...
    scene_data = fbx_data_from_scene(scene, settings)

    root = elem_empty(None, b"")  # Root element has no id, as it is not saved per se!

    # Mostly FBXHeaderExtension and GlobalSettings.
    fbx_header_elements(root, scene_data)

    # Documents and References are pretty much void currently.
    fbx_documents_elements(root, scene_data)
    fbx_references_elements(root, scene_data)

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

    # copy all collected files, if we did not embed them.
    if not media_settings.embed_textures:
        bpy_extras.io_utils.path_reference_copy(media_settings.copy_set)

    print('export finished in %.4f sec.' % (time.process_time() - start_time))
    return {'FINISHED'}


# defaults for applications, currently only unity but could add others.
def defaults_unity3d():
    return {
        "global_matrix": Matrix.Rotation(-math.pi / 2.0, 4, 'X'),
        "use_selection": False,
        "object_types": {'ARMATURE', 'EMPTY', 'MESH'},
        "use_mesh_modifiers": True,
        "use_armature_deform_only": True,
        "use_anim": True,
        "use_anim_optimize": False,
        "use_anim_action_all": True,
        "batch_mode": 'OFF',
        "use_default_take": True,
    }


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
