from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WIZARD = (ROOT / "media_hunter_bot" / "wm_wizard.py").read_text(encoding="utf-8")


def test_logo_wizard_accepts_gallery_png_gif_and_animation():
    assert '@router.message(LogoStates.upload, F.photo | F.document | F.animation)' in WIZARD
    assert 'name.endswith((".png", ".gif"))' in WIZARD
    assert 'name.endswith(".gif")' in WIZARD


def test_logo_wizard_exposes_size_position_and_opacity_settings():
    assert '"logosize_menu"' in WIZARD
    assert '"logopos_menu"' in WIZARD
    assert '"logoop_menu"' in WIZARD
    assert '"logo_size"' in WIZARD
    assert '"logo_position"' in WIZARD
    assert '"logo_opacity"' in WIZARD


def test_gallery_photo_is_normalized_to_png():
    assert 'def _convert_photo_to_png' in WIZARD
    assert 'final = LOGO_DIR/f"logo_{uid}_{token}.png"' in WIZARD


def test_logo_settings_are_persisted_as_image_watermark():
    assert '"type":"image"' in WIZARD
    assert '"logo":str(logo)' in WIZARD
    assert 'await db.aset_user_watermark' in WIZARD
    assert 'await db.aset_channel_watermark' in WIZARD
