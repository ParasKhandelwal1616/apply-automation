from pathlib import Path

from apply_bot.config import Profile, ensure_resume_copy


def test_ensure_resume_copy_uses_no_space_path(tmp_path: Path):
    original = tmp_path / "paras_resume_sept .pdf"
    original.write_bytes(b"%PDF-1.4")
    dest_dir = tmp_path / "data"
    profile = Profile(resume_path=str(original))
    fixed = ensure_resume_copy(profile, dest_dir)
    assert " " not in Path(fixed.resume_path).name
    assert Path(fixed.resume_path).exists()
    assert Path(fixed.resume_path).read_bytes() == b"%PDF-1.4"


def test_ensure_resume_copy_copies_unspaced_name(tmp_path: Path):
    original = tmp_path / "paras_resume_August.pdf"
    original.write_bytes(b"%PDF-august")
    dest_dir = tmp_path / "data"
    profile = Profile(resume_path=str(original))
    fixed = ensure_resume_copy(profile, dest_dir)
    dest = Path(fixed.resume_path)
    assert dest == dest_dir / "resume.pdf"
    assert dest.read_bytes() == b"%PDF-august"


def test_ensure_resume_copy_keeps_missing_path(tmp_path: Path):
    profile = Profile(resume_path=str(tmp_path / "missing .pdf"))
    fixed = ensure_resume_copy(profile, tmp_path / "data")
    assert fixed.resume_path.endswith("missing .pdf")
