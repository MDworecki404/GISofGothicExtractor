import io

from PIL import Image

from gothic_extract.g3.image import material_texture, ximg_to_png


def test_material_points_at_diffuse_texture(g3_fs):
    assert material_texture(g3_fs.find("G3_Nature_Ground_Grass_01_A.xshmat")) == "G3_Nature_Ground_Grass_01_Diffuse_01.ximg"


def test_find_by_file_name(g3_fs):
    assert g3_fs.find_name("g3_nature_ground_grass_01_diffuse_01.ximg")[:8] == b"GENOMFLE"
    assert g3_fs.find_name("nie_ma.ximg") is None


def test_dxt1_to_png_scaled(g3_fs):
    png, has_alpha = ximg_to_png(g3_fs.find_name("G3_Nature_Ground_Grass_01_Diffuse_01.ximg"), max_size=512)
    img = Image.open(io.BytesIO(png))
    assert img.size == (512, 512) and img.mode == "RGB" and not has_alpha
    r, g, b = img.resize((1, 1)).getpixel((0, 0))
    assert g > b  # grass


def test_formats_of_terrain_textures(g3_fs):
    from gothic_extract.g3.mesh import read_xcmsh

    mats = {el.material for p in g3_fs.list("G3_Myrtana_Landscape_01/", ".xcmsh")[:30] for el in read_xcmsh(g3_fs.find(p))}
    for m in mats:
        tex = material_texture(g3_fs.find_name(m))
        assert tex and ximg_to_png(g3_fs.find_name(tex), max_size=64)[0][:4] == b"\x89PNG", (m, tex)


def test_material_info_blend_modes(g3_fs):
    from gothic_extract.g3.image import material_info

    wall = material_info(g3_fs.find_name("G3_Architecture_WallHouse_01_A.xshmat"))
    assert wall.alpha_mode == "OPAQUE" and wall.texture == "G3_Architecture_WallHouse_01_Diffuse_01.ximg"  # its alpha is a detail map
    leaf = material_info(g3_fs.find_name("G3_Nature_Plant_Leaf_04_A.xshmat"))
    assert leaf.alpha_mode == "MASK" and leaf.mask_reference == 176
    assert material_info(g3_fs.find_name("BEARD.xshmat")).alpha_mode == "BLEND"
    assert material_info(g3_fs.find_name("G3_Myrtana_Water_Falls_01_A.xshmat")).alpha_mode == "BLEND"  # additive


def test_water_materials_have_no_colour_texture(g3_fs):
    from gothic_extract.g3.image import material_info

    river = material_info(g3_fs.find_name("G3_Myrtana_Water_River_01_A.xshmat"))
    ocean = material_info(g3_fs.find_name("G3_Myrtana_Water_Ocean_01_A.xshmat"))
    for water in (river, ocean):  # their samplers are normal maps, which are not a colour
        assert water.is_water and not water.hidden and water.texture is None and water.alpha_mode == "BLEND"
    for helper in ("G3_Myrtana_Water_Sea_01_A.xshmat", "G3_Myrtana_Rivermesh_Depth_01_A.xshmat"):
        assert material_info(g3_fs.find_name(helper)).hidden
    assert not material_info(g3_fs.find_name("G3_Architecture_WallHouse_01_A.xshmat")).is_water


def test_old_class_version_material_still_names_its_texture(g3_fs):
    # an eCResourceShaderMaterial_PS the property reader cannot parse (name and GUID before the properties)
    assert material_texture(g3_fs.find_name("G3_Objects_Interacts_Chest_Pod_02_A.xshmat")) == \
        "G3_Objects_Desert_Stuff_V_02_Diffuse_01.ximg"


def test_ximg_largest_mip_is_the_last_level():
    """Mip levels are stored smallest first: the 8x8 top level (4 blocks) follows 3 smaller levels (24 bytes)."""
    import io
    import struct

    from PIL import Image

    head = b"G3IMG\x02\x00/\x00" + struct.pack("<II", 8, 8)
    head += b"\x00" * (40 - len(head)) + b"DXT1" + struct.pack("<III", 1, 0, 0)
    red = bytes([0x00, 0xF8, 0x00, 0xF8, 0, 0, 0, 0])
    data = head + bytes(24) + red * 4
    png, _ = ximg_to_png(data, max_size=64)
    px = Image.open(io.BytesIO(png)).convert("RGB").getpixel((3, 3))
    assert px[0] > 200 and px[1] < 30 and px[2] < 30
