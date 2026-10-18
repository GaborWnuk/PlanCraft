import math

import pytest

from building import review


def test_small_build_keeps_default_render_distance():
    size = (46, 15, 26)
    assert review.render_distance(size, review.exterior_shots(size, 1)) == 10
    assert review.render_distance(size, []) == 10


def test_supertall_cameras_keep_far_side_of_build_in_view():
    size = (88, 313, 64)
    shots = review.exterior_shots(size, 1)
    chunks = review.render_distance(size, shots)
    assert chunks == 24
    for shot in shots:
        x, _, z = shot["pos"]
        reach = max(abs(x), abs(x - size[0]), abs(z), abs(z - size[2]))
        assert math.ceil(reach / 16) < chunks


def test_custom_cameras_are_included():
    assert review.render_distance((10, 10, 10), [{"pos": [-240, 5, 0]}]) == 17


def test_unrenderable_camera_is_rejected():
    with pytest.raises(ValueError, match="maximum 32"):
        review.render_distance((10, 10, 10), [{"pos": [600, 5, 0]}])
