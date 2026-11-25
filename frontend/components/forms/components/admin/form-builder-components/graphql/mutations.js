import { gql } from '@apollo/client';
import { FORM_FIELDS } from './queries.js';

export const SAVE_EVALUATION_FORM = gql`
    mutation SaveEvaluationForm($form_id: String!, $title: String!, $form_content: String!, $ai_enabled: Boolean) {
        saveEvaluationForm(form_id: $form_id, title: $title, form_content: $form_content, ai_enabled: $ai_enabled) {${FORM_FIELDS}}
    }
`;

// Save unpublished edits; the live form is untouched.
export const SAVE_FORM_DRAFT = gql`
    mutation SaveFormDraft($form_id: String!, $title: String!, $form_content: String!, $ai_enabled: Boolean) {
        saveEvaluationFormDraft(form_id: $form_id, title: $title, form_content: $form_content, ai_enabled: $ai_enabled) {${FORM_FIELDS}}
    }
`;

export const DISCARD_FORM_DRAFT = gql`
    mutation DiscardFormDraft($form_id: String!) {
        discardEvaluationFormDraft(form_id: $form_id) {${FORM_FIELDS}}
    }
`;

export const RESTORE_FORM_VERSION = gql`
    mutation RestoreFormVersion($form_id: String!, $version: Int!) {
        restoreEvaluationFormVersion(form_id: $form_id, version: $version) {${FORM_FIELDS}}
    }
`;

// Dry run of the AI on one call with the editor's current (unsaved) content. Saves nothing.
export const TEST_AI_FORM_EVALUATION = gql`
    mutation TestAIFormEvaluation($call_id: String!, $form_content: String!, $title: String) {
        testAIFormEvaluation(call_id: $call_id, form_content: $form_content, title: $title) {
            score
            total_score
            questions
            answered
            coverage
            unverified_evidence
            model
            answers {
                question_id
                label
                status
                value
                evidence
                timestamp
                confidence
                evidence_verified
                reason
            }
        }
    }
`;

export const DUPLICATE_FORM = gql`
    mutation DuplicateForm($form_id: String!, $title: String) {
        duplicateEvaluationForm(form_id: $form_id, title: $title) {${FORM_FIELDS}}
    }
`;

export const DELETE_EVALUATION_FORM = gql`
    mutation DeleteEvaluationForm($id: ID!) {
        deleteEvaluationForm(id: $id)
    }
`;

export const SAVE_EVALUATION_RESPONSE = gql`
    mutation SaveEvaluationResponse($inum: String, $form_id: String!, $call_id: String, $responses: String, $tags: String, $user_id: ID, $score: Float) {
        saveEvaluationResponse(inum: $inum, form_id: $form_id, call_id: $call_id, responses: $responses, tags: $tags, user_id: $user_id, score: $score) {
            id
            form_id
            call_id
            score
        }
    }
`;

export const UPDATE_EVALUATION_RESPONSE = gql`
    mutation UpdateEvaluationResponse($id: ID!, $form_id: String, $call_id: String, $responses: String, $tags: String, $score: Float) {
        updateEvaluationResponse(id: $id, form_id: $form_id, call_id: $call_id, responses: $responses, tags: $tags, score: $score) {
            id
            form_id
            call_id
            score
            updatedAt
        }
    }
`;

export const DELETE_EVALUATION_RESPONSE = gql`
    mutation DeleteEvaluationResponse($id: ID!) {
        deleteEvaluationResponse(id: $id)
    }
`;

export const RUN_AI_FORM_EVALUATION = gql`
    mutation RunAIFormEvaluation($call_id: String!, $form_id: String!) {
        runAIFormEvaluation(call_id: $call_id, form_id: $form_id) {
            status
            message
        }
    }
`;

export const BACKFILL_AI_FORM_EVALUATION = gql`
    mutation BackfillAIFormEvaluation($form_id: String!, $date_from: String, $date_to: String, $dry_run: Boolean) {
        backfillAIFormEvaluation(form_id: $form_id, date_from: $date_from, date_to: $date_to, dry_run: $dry_run) {
            eligible
            truncated
            queued
            max_calls
        }
    }
`;
