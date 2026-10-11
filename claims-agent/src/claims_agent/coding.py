"""Integration boundary for a future approved coding-validation provider.

No implementation, compatibility table, network client, or provider is selected.
The application must authenticate/configure the provider at the integration
boundary; user-authored source labels must not grant trust in production.
"""

from typing import Protocol

from .schemas import CodingAssessment, CodingRequest


class CodingAssessmentProvider(Protocol):
    def assess(self, request: CodingRequest) -> CodingAssessment:
        """Assess these exact codes for this review, preserving source and reason.

        Return unknown if consistency cannot be established. Integration code
        must handle provider failures without substituting a consistent result.
        """
        ...
