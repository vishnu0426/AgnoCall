import { useState } from 'react';
import { useMutation } from '@apollo/client/react';
import { Modal, Input, Switch, Form, Select } from 'antd';
import {
    SAVE_EVALUATION_FORM, SAVE_FORM_DRAFT, DISCARD_FORM_DRAFT, RESTORE_FORM_VERSION, DUPLICATE_FORM,
    DELETE_EVALUATION_FORM,
} from '../graphql/mutations.js';
import { GET_AI_EVALUATION_LIMITS } from '../graphql/queries.js';
import { getDefaultFormContent } from '../constants/fieldDefaults.js';
import { DEFAULT_LANGUAGE, languageOptions, getLanguage } from '../constants/languages.js';
import { autoTranslateFields } from '../../../../utils/i18n.js';
import { useToast } from '../../../../context/ToastContext.jsx';

const resetCreateModal = () => ({
    open: false,
    formName: '',
    hasScoring: true,
    languages: [DEFAULT_LANGUAGE],
    defaultLanguage: DEFAULT_LANGUAGE,
});

export const useFormOperations = (selectedForm, formTitle, formFields, formSettings, formTheme, refetch, setFormFields) => {
    const { showToast } = useToast();
    const [saveForm] = useMutation(SAVE_EVALUATION_FORM);
    const [saveDraftMutation] = useMutation(SAVE_FORM_DRAFT);
    const [discardDraftMutation] = useMutation(DISCARD_FORM_DRAFT);
    const [restoreMutation] = useMutation(RESTORE_FORM_VERSION);
    const [duplicateMutation] = useMutation(DUPLICATE_FORM);
    const [deleteForm] = useMutation(DELETE_EVALUATION_FORM);
    const [createModal, setCreateModal] = useState(resetCreateModal());
    const [translating, setTranslating] = useState(false);

    const buildContent = (fields) => JSON.stringify({
        fields,
        total_score: formSettings.totalScore,
        hasScoring: formSettings.hasScoring,
        theme: formTheme,
        languages: formSettings.languages && formSettings.languages.length > 0
            ? formSettings.languages
            : [DEFAULT_LANGUAGE],
        default_language: formSettings.defaultLanguage || DEFAULT_LANGUAGE,
    });

    // Fill missing translations before anything is stored (never overwrites manual edits).
    const prepareFields = async () => {
        const languages = formSettings.languages || [DEFAULT_LANGUAGE];
        const defaultLang = formSettings.defaultLanguage || DEFAULT_LANGUAGE;
        if (languages.length <= 1) return formFields;
        setTranslating(true);
        try {
            const { fields: translated, translatedCount, failed } =
                await autoTranslateFields(formFields, languages, defaultLang);
            if (translatedCount > 0 && setFormFields) setFormFields(translated);
            if (failed) showToast('Auto-translation unavailable — missing translations were left empty', 'info');
            return translated;
        } finally {
            setTranslating(false);
        }
    };

    const variablesFor = (fields) => ({
        form_id: selectedForm.form_id,
        title: formTitle,
        form_content: buildContent(fields),
        ai_enabled: !!formSettings.aiEnabled,
    });

    /** Store the edits as a draft. The live form is untouched. Returns the saved form, or null. */
    const saveDraft = async () => {
        if (!selectedForm) { showToast('Select or create a form first', 'info'); return null; }
        try {
            const fields = await prepareFields();
            const res = await saveDraftMutation({ variables: variablesFor(fields) });
            showToast('Draft saved. It is not live until you publish.', 'success');
            if (refetch) refetch();
            return res?.data?.saveEvaluationFormDraft || null;
        } catch (err) {
            showToast(err?.message ? `Could not save the draft: ${err.message}` : 'Could not save the draft', 'error');
            return null;
        }
    };

    /** Make the edits the live version. Returns the published form, or null. */
    const publish = async () => {
        if (!selectedForm) { showToast('Select or create a form first', 'info'); return null; }
        try {
            const fields = await prepareFields();
            const res = await saveForm({
                variables: variablesFor(fields),
                refetchQueries: [{ query: GET_AI_EVALUATION_LIMITS }],
            });
            showToast('Published. This is now the live version.', 'success');
            if (refetch) refetch();
            return res?.data?.saveEvaluationForm || null;
        } catch (err) {
            // Server-side guardrails (AI cap, invalid AI form, permissions) come back with a readable message.
            showToast(err?.message ? `Could not publish: ${err.message}` : 'Could not publish the form', 'error');
            return null;
        }
    };

    /** Throw the draft away; returns the form as it is live. */
    const discardDraft = async () => {
        if (!selectedForm) return null;
        try {
            const res = await discardDraftMutation({ variables: { form_id: selectedForm.form_id } });
            showToast('Draft discarded.', 'success');
            if (refetch) refetch();
            return res?.data?.discardEvaluationFormDraft || null;
        } catch (err) {
            showToast(err?.message ? `Could not discard the draft: ${err.message}` : 'Could not discard the draft', 'error');
            return null;
        }
    };

    /** Load an older published version into the draft; returns the form (with the draft). */
    const restoreVersion = async (version) => {
        try {
            const res = await restoreMutation({ variables: { form_id: selectedForm.form_id, version } });
            showToast(`Version ${version} loaded as a draft. Review it, then publish.`, 'success');
            if (refetch) refetch();
            return res?.data?.restoreEvaluationFormVersion || null;
        } catch (err) {
            showToast(err?.message ? `Could not restore: ${err.message}` : 'Could not restore that version', 'error');
            return null;
        }
    };

    /** A copy of a form's LIVE content, with AI evaluation off. Returns the new form. */
    const duplicate = async (form) => {
        try {
            const res = await duplicateMutation({ variables: { form_id: form.form_id } });
            showToast('Copy created. AI evaluation is off on the copy.', 'success');
            if (refetch) refetch();
            return res?.data?.duplicateEvaluationForm || null;
        } catch (err) {
            showToast(err?.message ? `Could not copy the form: ${err.message}` : 'Could not copy the form', 'error');
            return null;
        }
    };

    const handleDelete = async (id) => {
        try {
            await deleteForm({ variables: { id } });
            showToast('Form deleted successfully!', 'success');
            refetch();
            return true;
        } catch (err) {
            showToast('Error deleting form', 'error');
            return false;
        }
    };

    const handleCreateNew = () => {
        setCreateModal({ ...resetCreateModal(), open: true });
    };

    const handleCreateConfirm = async () => {
        if (!createModal.formName.trim()) {
            showToast('Enter a form name', 'error');
            return;
        }
        if (!createModal.languages || createModal.languages.length === 0) {
            showToast('Select at least one language', 'error');
            return;
        }
        try {
            const formId = `form_${Date.now()}`;
            const formContent = JSON.stringify({
                ...getDefaultFormContent(),
                hasScoring: createModal.hasScoring,
                languages: createModal.languages,
                default_language: createModal.defaultLanguage,
            });
            await saveForm({
                variables: {
                    form_id: formId,
                    title: createModal.formName,
                    form_content: formContent,
                },
            });
            showToast(
                `Form created successfully! (${createModal.languages.map(l => getLanguage(l).native).join(', ')})`,
                'success'
            );
            setCreateModal(resetCreateModal());
            refetch();
        } catch (err) {
            showToast('Error creating form', 'error');
        }
    };

    const CreateModal = (
        <Modal
            title="Create New Form"
            open={createModal.open}
            onOk={handleCreateConfirm}
            onCancel={() => setCreateModal(resetCreateModal())}
            okText="Create"
            cancelText="Cancel"
            width={520}
        >
            <Form layout="vertical">
                <Form.Item label="Form Name">
                    <Input
                        value={createModal.formName}
                        onChange={(e) => setCreateModal(prev => ({ ...prev, formName: e.target.value }))}
                        placeholder="Enter form name"
                    />
                </Form.Item>
                <Form.Item label="Enable Scoring">
                    <Switch
                        checked={createModal.hasScoring}
                        onChange={(val) => setCreateModal(prev => ({ ...prev, hasScoring: val }))}
                    />
                </Form.Item>
                <Form.Item
                    label="Languages"
                    extra="Pick every language the form will be offered in — each shown in its own script."
                >
                    <Select
                        mode="multiple"
                        showSearch
                        optionFilterProp="label"
                        placeholder="Select languages (e.g. English, हिन्दी, العربية)"
                        value={createModal.languages}
                        onChange={(vals) => setCreateModal(prev => {
                            // Keep the default language inside the selection
                            let defaultLang = prev.defaultLanguage;
                            if (!vals.includes(defaultLang)) defaultLang = vals[0] || DEFAULT_LANGUAGE;
                            return { ...prev, languages: vals, defaultLanguage: defaultLang };
                        })}
                        options={languageOptions()}
                        maxTagCount="responsive"
                        style={{ width: '100%' }}
                    />
                </Form.Item>
                <Form.Item
                    label="Default Language"
                    extra="The language you write fields in. Other languages are auto-translated from it."
                >
                    <Select
                        showSearch
                        optionFilterProp="label"
                        value={createModal.defaultLanguage}
                        onChange={(val) => setCreateModal(prev => ({ ...prev, defaultLanguage: val }))}
                        options={languageOptions(createModal.languages)}
                        style={{ width: '100%' }}
                    />
                </Form.Item>
            </Form>
        </Modal>
    );

    return { buildContent, saveDraft, publish, discardDraft, restoreVersion, duplicate, handleDelete, handleCreateNew, CreateModal, translating };
};
