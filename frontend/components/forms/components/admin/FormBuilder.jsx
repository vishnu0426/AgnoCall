import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { useQuery } from '@apollo/client/react';
import { Spin } from 'antd';
import { GET_EVALUATION_FORMS } from './form-builder-components/graphql/queries.js';
import { useFormOperations } from './form-builder-components/hooks/useFormOperations.jsx';
import { useFieldOperations } from './form-builder-components/hooks/useFieldOperations.js';
import { useDragAndDrop } from './form-builder-components/hooks/useDragAndDrop.js';
import FormsLibrary from './form-builder-components/ui/FormsLibrary/FormsLibrary.jsx';
import BuilderHeader from './form-builder-components/ui/BuilderHeader/BuilderHeader.jsx';
import FieldPalette from './form-builder-components/ui/FieldPalette/FieldPalette.jsx';
import BuilderCanvas from './form-builder-components/ui/BuilderCanvas/BuilderCanvas.jsx';
import FieldSettings from './form-builder-components/ui/FieldSettings/FieldSettings.jsx';
import PreviewModal from './form-builder-components/ui/PreviewModal/PreviewModal.jsx';
import FormThemeSettings from './form-builder-components/ui/FormThemeSettings/FormThemeSettings.jsx';
import PublishModal from './form-builder-components/ui/PublishModal/PublishModal.jsx';
import VersionHistoryModal from './form-builder-components/ui/VersionHistory/VersionHistoryModal.jsx';
import TryOnCallModal from './form-builder-components/ui/TryOnCall/TryOnCallModal.jsx';
import { redistributeScores, rescaleFieldsToTotal } from './form-builder-components/constants/fieldDefaults.js';
import { validateForm } from './form-builder-components/constants/validateForm.js';

const DEFAULT_THEME = { mode: 'dark', backgroundColor: '#000000', backgroundImage: '', primaryColor: '#14b8a6' };
const DEFAULT_SETTINGS = { hasScoring: false, totalScore: 100, languages: ['en'], defaultLanguage: 'en', aiEnabled: false };
const LEAVE_MESSAGE = 'You have unsaved changes in this form. Leave without saving?';

// What the editor holds, as one comparable string. "Unsaved changes" = this differs from the baseline.
const snapshotOf = (title, fields, settings, theme) => JSON.stringify({ title, fields, settings, theme });

/**
 * The editor shows the form's DRAFT when it has one, otherwise the live version. (The live version is what
 * the AI and reviewers use; a draft is work in progress that only goes live when published.)
 */
const editorStateFrom = (form) => {
    const useDraft = !!form.has_draft && !!form.draft_content;
    const content = JSON.parse(useDraft ? form.draft_content : form.form_content);
    return {
        title: (useDraft && form.draft_title) || form.title,
        fields: content.fields || [],
        settings: {
            hasScoring: content.hasScoring || false,
            totalScore: content.total_score || 100,
            languages: content.languages?.length ? content.languages : ['en'],
            defaultLanguage: content.default_language || 'en',
            aiEnabled: useDraft && form.draft_ai_enabled != null ? !!form.draft_ai_enabled : !!form.ai_enabled,
        },
        theme: content.theme || DEFAULT_THEME,
    };
};

const FormBuilder = () => {
    const { loading, data, refetch } = useQuery(GET_EVALUATION_FORMS);
    const [selectedForm, setSelectedForm] = useState(null);
    const [selectedField, setSelectedField] = useState(null);
    const [showPreview, setShowPreview] = useState(false);
    const [showThemeSettings, setShowThemeSettings] = useState(false);
    const [showHistory, setShowHistory] = useState(false);
    const [showTryAI, setShowTryAI] = useState(false);
    const [restoring, setRestoring] = useState(null);
    const [publishDialog, setPublishDialog] = useState({ open: false, issues: [] });
    const [publishing, setPublishing] = useState(false);
    const [formTitle, setFormTitle] = useState('');
    const [formFields, setFormFields] = useState([]);
    const [formSettings, setFormSettings] = useState(DEFAULT_SETTINGS);
    const [formTheme, setFormTheme] = useState(DEFAULT_THEME);
    const [baseline, setBaseline] = useState('');

    const { buildContent, saveDraft, publish, discardDraft, restoreVersion, duplicate, handleDelete, handleCreateNew, CreateModal, translating } =
        useFormOperations(selectedForm, formTitle, formFields, formSettings, formTheme, refetch, setFormFields);
    const { addField, updateField, deleteField, duplicateField } = useFieldOperations(
        formFields, setFormFields, selectedField, setSelectedField
    );
    const { handleDragStart, handlePaletteDragStart, handleDragOver, handleCanvasDrop, ghostIndex } = useDragAndDrop(
        formFields, setFormFields, addField
    );

    // Load a server form into the editor (and make it the baseline for "unsaved changes").
    const applyEditorState = useCallback((form) => {
        const state = editorStateFrom(form);
        setSelectedForm(form);
        setFormTitle(state.title);
        setFormFields(state.fields);
        setFormSettings(state.settings);
        setFormTheme(state.theme);
        setBaseline(snapshotOf(state.title, state.fields, state.settings, state.theme));
        setSelectedField((prev) => (prev ? state.fields.find((f) => f.id === prev.id) || null : null));
    }, []);

    useEffect(() => {
        if (data?.getEvaluationForms?.length > 0 && !selectedForm) {
            applyEditorState(data.getEvaluationForms[0]);
        }
    }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

    // Keep the server-owned facts about the open form (version, draft flag...) current without touching
    // what the person is editing.
    useEffect(() => {
        if (!selectedForm || !data?.getEvaluationForms) return;
        const fresh = data.getEvaluationForms.find((f) => f.form_id === selectedForm.form_id);
        if (fresh && fresh.updatedAt !== selectedForm.updatedAt) setSelectedForm(fresh);
    }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

    const dirty = useMemo(
        () => !!selectedForm && baseline !== '' && snapshotOf(formTitle, formFields, formSettings, formTheme) !== baseline,
        [selectedForm, baseline, formTitle, formFields, formSettings, formTheme]
    );
    const status = dirty ? 'unsaved' : selectedForm?.has_draft ? 'draft' : 'published';

    // --- protect unsaved work -------------------------------------------------------------------------
    const confirmDiscard = () => !dirty || window.confirm(LEAVE_MESSAGE);

    useEffect(() => {
        if (!dirty) return undefined;
        const beforeUnload = (e) => { e.preventDefault(); e.returnValue = ''; };
        // Links inside the app (sidebar, etc.) don't reload the page, so beforeunload never sees them.
        const onClick = (e) => {
            const a = e.target?.closest?.('a[href]');
            if (!a || a.target === '_blank' || e.metaKey || e.ctrlKey || e.shiftKey) return;
            const url = new URL(a.href, window.location.href);
            if (url.origin !== window.location.origin) return;
            if (url.pathname === window.location.pathname && url.search === window.location.search) return;
            if (!window.confirm(LEAVE_MESSAGE)) { e.preventDefault(); e.stopPropagation(); }
        };
        window.addEventListener('beforeunload', beforeUnload);
        document.addEventListener('click', onClick, true);
        return () => {
            window.removeEventListener('beforeunload', beforeUnload);
            document.removeEventListener('click', onClick, true);
        };
    }, [dirty]);

    // --- actions ---------------------------------------------------------------------------------------------
    const handleSelectForm = (form) => {
        if (form.id === selectedForm?.id) return;
        if (!confirmDiscard()) return;
        applyEditorState(form);
        setSelectedField(null);
    };

    const handleSaveDraft = async () => {
        const saved = await saveDraft();
        if (saved) applyEditorState(saved);
    };

    const doPublish = async () => {
        setPublishing(true);
        const published = await publish();
        setPublishing(false);
        setPublishDialog({ open: false, issues: [] });
        if (published) applyEditorState(published);
    };

    const requestPublish = () => {
        const issues = validateForm(formFields, formSettings);
        const aiLive = !!selectedForm?.ai_enabled || !!formSettings.aiEnabled;
        if (issues.length === 0 && !aiLive) {
            doPublish();
        } else {
            setPublishDialog({ open: true, issues });
        }
    };

    const handleDiscard = async () => {
        if (!selectedForm) return;
        if (selectedForm.has_draft) {
            const live = await discardDraft();     // back to the live version
            if (live) applyEditorState(live);
        } else {
            applyEditorState(selectedForm);        // only local edits: back to what was loaded
        }
    };

    const handleRestore = async (version) => {
        if (!confirmDiscard()) return;
        setRestoring(version);
        const form = await restoreVersion(version);
        setRestoring(null);
        if (form) {
            applyEditorState(form);
            setShowHistory(false);
        }
    };

    const handleDeleteForm = async (id) => {
        const ok = await handleDelete(id);
        if (ok && selectedForm?.id === id) {
            setSelectedForm(null);
            setFormTitle('');
            setFormFields([]);
            setBaseline('');
            setSelectedField(null);
        }
    };

    const handleDuplicate = async (form) => {
        const copy = await duplicate(form);
        if (copy && confirmDiscard()) applyEditorState(copy);
    };

    const handleCreate = () => {
        if (confirmDiscard()) handleCreateNew();
    };

    const handleUpdateField = (id, updates) => {
        // Auto-redistribute: changing a field's max_score keeps the form total constant
        if (updates.max_score !== undefined && formSettings.hasScoring) {
            const total = formSettings.totalScore || 100;
            const newScore = Math.max(0, Math.min(updates.max_score, total));
            const newFields = redistributeScores(formFields, id, newScore, total);
            setFormFields(newFields);
            if (selectedField?.id === id) {
                setSelectedField({ ...selectedField, ...updates, max_score: newScore });
            }
            return;
        }
        updateField(id, updates);
    };

    // Changing Total Max Score rescales every scorable field proportionally
    const handleTotalScoreChange = (val) => {
        const newTotal = val || 100;
        setFormSettings(prev => ({ ...prev, totalScore: newTotal }));
        if (formSettings.hasScoring && formFields.length > 0) {
            const rescaled = rescaleFieldsToTotal(formFields, newTotal);
            setFormFields(rescaled);
            if (selectedField) {
                const updated = rescaled.find(f => f.id === selectedField.id);
                if (updated) setSelectedField(updated);
            }
        }
    };

    if (loading) {
        return (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
                <Spin size="large" />
            </div>
        );
    }

    return (
        <div className="form-builder-studio">
            <FormsLibrary
                forms={data?.getEvaluationForms || []}
                selectedForm={selectedForm}
                onSelectForm={handleSelectForm}
                onDelete={handleDeleteForm}
                onDuplicate={handleDuplicate}
                onCreate={handleCreate}
                loading={loading}
            />
            <div className="builder-main-area">
                <BuilderHeader
                    form={selectedForm ? { ...selectedForm, title: formTitle } : null}
                    formFields={formFields}
                    formSettings={formSettings}
                    setFormSettings={setFormSettings}
                    onTotalScoreChange={handleTotalScoreChange}
                    onRename={setFormTitle}
                    status={status}
                    dirty={dirty}
                    onSaveDraft={handleSaveDraft}
                    onPublish={requestPublish}
                    onDiscard={handleDiscard}
                    onHistory={() => setShowHistory(true)}
                    onTryAI={() => setShowTryAI(true)}
                    onPreview={() => setShowPreview(true)}
                    onThemeSettings={() => setShowThemeSettings(true)}
                    translating={translating}
                    publishing={publishing}
                />
                <div className="builder-workspace">
                    <FieldPalette onDragStart={handlePaletteDragStart} onAddField={addField} />
                    <BuilderCanvas
                        fields={formFields}
                        selectedField={selectedField}
                        onSelectField={setSelectedField}
                        onUpdateField={handleUpdateField}
                        onDeleteField={deleteField}
                        onDuplicateField={duplicateField}
                        onDragStart={handleDragStart}
                        onDragOver={handleDragOver}
                        onDrop={handleCanvasDrop}
                        ghostIndex={ghostIndex}
                        onAddField={() => addField('text')}
                        hasScoring={formSettings.hasScoring}
                    />
                    <FieldSettings
                        field={selectedField}
                        onUpdate={handleUpdateField}
                        formSettings={formSettings}
                        fields={formFields}
                    />
                </div>
            </div>
            <PreviewModal
                open={showPreview}
                onClose={() => setShowPreview(false)}
                form={selectedForm}
                fields={formFields}
                formTheme={formTheme}
                languages={formSettings.languages}
                defaultLanguage={formSettings.defaultLanguage}
            />
            <FormThemeSettings
                open={showThemeSettings}
                onClose={() => setShowThemeSettings(false)}
                theme={formTheme}
                onChange={setFormTheme}
            />
            <PublishModal
                open={publishDialog.open}
                issues={publishDialog.issues}
                aiLive={!!selectedForm?.ai_enabled || !!formSettings.aiEnabled}
                busy={publishing}
                onConfirm={doPublish}
                onClose={() => setPublishDialog({ open: false, issues: [] })}
                onFocusField={(id) => {
                    setPublishDialog({ open: false, issues: [] });
                    setSelectedField(formFields.find((f) => f.id === id) || null);
                }}
            />
            <VersionHistoryModal
                open={showHistory}
                form={selectedForm}
                onClose={() => setShowHistory(false)}
                onRestore={handleRestore}
                restoring={restoring}
            />
            <TryOnCallModal
                open={showTryAI}
                onClose={() => setShowTryAI(false)}
                getContent={() => buildContent(formFields)}
                title={formTitle}
                questionCount={formFields.length}
            />
            {CreateModal}
        </div>
    );
};

export default FormBuilder;
