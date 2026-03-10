# Distilled Spirits Label Rules (Prototype Simplification)

This document defines simplified verification rules used by the prototype.

These rules represent common reviewer checks and are not a full regulatory implementation.

---

# Required Label Elements

The label must contain:

1. Brand Name
2. Class / Type
3. Alcohol Content
4. Net Contents
5. Bottler / Producer
6. Government Warning Statement

Imports must also include:

7. Country of Origin

---

# Alcohol Content

Common formats:

45% Alc./Vol.  
45% Alcohol by Volume  
90 Proof

System behavior:

1. extract ABV percentage
2. convert proof when present
3. compare normalized values

Example:

45% ABV equals 90 proof.

---

# Net Contents

Typical formats:

750 ml  
750ML  
750 mL

Normalization rules:

- ignore case
- normalize whitespace
- normalize unit formatting

---

# Brand Name

Brand names may vary in:

- capitalization
- punctuation
- apostrophes

Examples:

Stone's Throw  
STONE’S THROW  
STONES THROW

These typically count as normalized_match.

---

# Class / Type

Examples include:

Whiskey  
Vodka  
Rum  
Gin  
Tequila

Matching is case-insensitive.

---

# Bottler / Producer

The system should look for phrases such as:

Bottled by  
Produced by  
Distilled by

Exact string matching is not required.

If uncertain:

status = review.

---

# Government Warning Statement

The label must contain the government warning text.

Typical prefix:

GOVERNMENT WARNING:

Checks:

1. presence of warning statement
2. approximate content match

Minor punctuation differences may be tolerated.

If the warning cannot be confidently detected:

status = review.

---

# Status Definitions

match

Exact match.

normalized_match

Equivalent after normalization.

mismatch

Clear difference between label and application.

review

Insufficient certainty.

---

# Principle

When uncertain:

return review.

Never produce false certainty.
