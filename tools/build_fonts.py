"""Build the bundled watermark fonts (static, Latin + Cyrillic subset).

Source: a sparse checkout of https://github.com/google/fonts (OFL / UFL).
Usage: python tools/build_fonts.py /path/to/google-fonts-checkout
Variable fonts are instanced to one weight so FFmpeg drawtext and the Mini
App render exactly the same face.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

# id: (source file, weight for variable fonts or None, license dir)
FONTS = {
    "montserrat": ("ofl/montserrat/Montserrat[wght].ttf", 800, "ofl/montserrat"),
    "manrope": ("ofl/manrope/Manrope[wght].ttf", 800, "ofl/manrope"),
    "rubik": ("ofl/rubik/Rubik[wght].ttf", 700, "ofl/rubik"),
    "unbounded": ("ofl/unbounded/Unbounded[wght].ttf", 700, "ofl/unbounded"),
    "oswald": ("ofl/oswald/Oswald[wght].ttf", 600, "ofl/oswald"),
    "russo": ("ofl/russoone/RussoOne-Regular.ttf", None, "ofl/russoone"),
    "ptsans": ("ofl/ptsans/PT_Sans-Web-Regular.ttf", None, "ofl/ptsans"),
    "ptsans_bold": ("ofl/ptsans/PT_Sans-Web-Bold.ttf", None, "ofl/ptsans"),
    "ptserif": ("ofl/ptserif/PT_Serif-Web-Regular.ttf", None, "ofl/ptserif"),
    "playfair": ("ofl/playfairdisplay/PlayfairDisplay[wght].ttf", 700, "ofl/playfairdisplay"),
    "comfortaa": ("ofl/comfortaa/Comfortaa[wght].ttf", 700, "ofl/comfortaa"),
    "caveat": ("ofl/caveat/Caveat[wght].ttf", 700, "ofl/caveat"),
    "lobster": ("ofl/lobster/Lobster-Regular.ttf", None, "ofl/lobster"),
    "marck": ("ofl/marckscript/MarckScript-Regular.ttf", None, "ofl/marckscript"),
    "pixel": ("ofl/pressstart2p/PressStart2P-Regular.ttf", None, "ofl/pressstart2p"),
}
UNICODES = "U+0020-007E,U+00A0-00FF,U+0400-045F,U+0490-0491,U+2010-2027,U+2030-203A,U+20AC,U+20BD,U+2116,U+2122"


def main(src: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    lic = out / "licenses"
    lic.mkdir(exist_ok=True)
    for fid, (rel, weight, lic_dir) in FONTS.items():
        font = TTFont(src / rel)
        if weight is not None and "fvar" in font:
            font = instantiateVariableFont(font, {"wght": weight}, updateFontNames=True)
        opts = subset.Options()
        opts.layout_features = ["*"]
        opts.name_IDs = ["*"]
        opts.notdef_outline = True
        sub = subset.Subsetter(opts)
        sub.populate(unicodes=subset.parse_unicodes(UNICODES))
        sub.subset(font)
        if 0x0416 not in font.getBestCmap():
            raise SystemExit(f"{fid}: no Cyrillic")
        font.save(out / f"{fid}.ttf")
        for name in ("OFL.txt", "UFL.txt", "LICENSE.txt"):
            f = src / lic_dir / name
            if f.exists():
                shutil.copy(f, lic / f"{Path(lic_dir).name}-{name}")
        print(fid, (out / f"{fid}.ttf").stat().st_size)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(__file__).resolve().parents[1] / "media_hunter_bot" / "fonts")
