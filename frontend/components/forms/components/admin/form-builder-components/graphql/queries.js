import { gql } from '@apollo/client';

// Every field the builder needs about a form (live content + any unpublished draft).
export const FORM_FIELDS = `
            id
            form_id
            title
            form_content
            ai_enabled
            version
            createdAt
            updatedAt
            has_draft
            draft_title
            draft_content
            draft_ai_enabled
            draft_updatedAt
`;

export const GET_EVALUATION_FORMS = gql`
    query GetEvaluationForms {
        getEvaluationForms {${FORM_FIELDS}}
    }
`;

export const GET_CALLS_FOR_FORM_TEST = gql`
    query GetCallsForFormTest {
        getCallsForFormTest(limit: 25) {
            id
            filename
            call_date
            duration_seconds
        }
    }
`;

export const GET_FORM_VERSIONS = gql`
    query GetFormVersions($form_id: String!) {
        getEvaluationFormVersions(form_id: $form_id) {
            version
            title
            publishedAt
            is_current
        }
    }
`;

export const GET_AI_EVALUATION_LIMITS = gql`
    query GetAIEvaluationLimits {
        getAIEvaluationLimits {
            feature_enabled
            enabled_count
            max_enabled_forms
            max_questions
        }
    }
`;

export const GET_EVALUATION_FORM = gql`
    query GetEvaluationForm($id: ID!) {
        getEvaluationForm(id: $id) {
            id
            form_id
            title
            form_content
            createdAt
        }
    }
`;

export const GET_EVALUATION_RESPONSES = gql`
    query GetEvaluationResponses($call_id: String) {
        getEvaluationResponses(call_id: $call_id) {
            id
            form_id
            call_id
            responses
            score
            source
            form_version
            evidence
            createdAt
            updatedAt
        }
    }
`;

export const GET_EVALUATION_RESPONSE = gql`
    query GetEvaluationResponse($id: ID!) {
        getEvaluationResponse(id: $id) {
            id
            form_id
            call_id
            responses
            score
            createdAt
            updatedAt
        }
    }
`;

export const TRANSLATE_TEXTS = gql`
    query TranslateTexts($texts: [String!]!, $target: String!, $source: String) {
        translateTexts(texts: $texts, target: $target, source: $source)
    }
`;
