"""What the recorder writes for the viewer."""
from twin.engine.accidents import CAR_WIDTH_M
from twin.engine.vehicle_dynamics import AMBULANCE_SPEC, CAR_SPEC
from twin.world import scenarios
from twin.world.record import map_section


def test_map_section_gives_the_vehicle_body_size_the_viewer_fits_models_into():
    vehicle = map_section(scenarios.build("city").sim)["vehicle"]
    assert vehicle == {"length": CAR_SPEC.length, "width": CAR_WIDTH_M}
    assert AMBULANCE_SPEC.length == CAR_SPEC.length  # one body size for every vehicle, for now
