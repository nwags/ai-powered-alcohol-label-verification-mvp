from enum import Enum


class VerificationField(str, Enum):
    BRAND_NAME = "brand_name"
    CLASS_TYPE = "class_type"
    ALCOHOL_CONTENT = "alcohol_content"
    NET_CONTENTS = "net_contents"
    BOTTLER_PRODUCER = "bottler_producer"
    COUNTRY_OF_ORIGIN = "country_of_origin"
    GOVERNMENT_WARNING = "government_warning"


class FieldStatus(str, Enum):
    MATCH = "match"
    NORMALIZED_MATCH = "normalized_match"
    MISMATCH = "mismatch"
    REVIEW = "review"


class OverallStatus(str, Enum):
    MATCH = "match"
    NORMALIZED_MATCH = "normalized_match"
    MISMATCH = "mismatch"
    REVIEW = "review"
