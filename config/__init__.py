from config.schema import (
    SchoolConfig,
    SchoolType,
    TimeGridConfig,
    LessonSlot,
    PauseSlot,
    DoubleBlock,
    GradeConfig,
    GradeDefinition,
    TeacherConfig,
    RoomConfig,
    SpecialRoomDef,
    CouplingConfig,
    SolverConfig,
)
from config.defaults import (
    default_school_config,
    default_time_grid,
    default_grades,
    default_rooms,
    STUNDENTAFEL_LEGACY,
    SUBJECT_METADATA,
)
from config.nrw_g9 import STUNDENTAFEL_NRW_G9
from config.manager import ConfigManager

__all__ = [
    "SchoolConfig",
    "SchoolType",
    "TimeGridConfig",
    "LessonSlot",
    "PauseSlot",
    "DoubleBlock",
    "GradeConfig",
    "GradeDefinition",
    "TeacherConfig",
    "RoomConfig",
    "SpecialRoomDef",
    "CouplingConfig",
    "SolverConfig",
    "default_school_config",
    "default_time_grid",
    "default_grades",
    "default_rooms",
    "STUNDENTAFEL_LEGACY",
    "STUNDENTAFEL_NRW_G9",
    "SUBJECT_METADATA",
    "ConfigManager",
]
