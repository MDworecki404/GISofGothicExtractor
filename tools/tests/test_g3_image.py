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
