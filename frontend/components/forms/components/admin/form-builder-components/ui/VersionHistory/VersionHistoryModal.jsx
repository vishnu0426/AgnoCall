import React, { useEffect } from 'react';
import { useLazyQuery } from '@apollo/client/react';
import { Button, Empty, List, Modal, Spin, Tag, Typography } from 'antd';
import { GET_FORM_VERSIONS } from '../../graphql/queries.js';
import { formatWhen } from '../FormsLibrary/FormCard.jsx';

const { Text } = Typography;

const when = (iso) => {
    const d = iso ? new Date(iso) : null;
    if (!d || Number.isNaN(d.getTime())) return '';
    return `${formatWhen(iso)}, ${d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}`;
};

/** Published revisions of one form. "Restore" puts an old one into the DRAFT; nothing goes live by itself. */
const VersionHistoryModal = ({ open, form, onClose, onRestore, restoring }) => {
    const [load, { data, loading }] = useLazyQuery(GET_FORM_VERSIONS, { fetchPolicy: 'network-only' });
    useEffect(() => {
        if (open && form) load({ variables: { form_id: form.form_id } });
    }, [open, form?.form_id]); // eslint-disable-line react-hooks/exhaustive-deps

    const versions = data?.getEvaluationFormVersions || [];
    return (
        <Modal open={open} onCancel={onClose} title="Version history" footer={<Button onClick={onClose}>Close</Button>} width={520}>
            <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
                Every time a form is published, that version is kept. Restoring an older one loads it into your draft so you can review it before publishing.
            </Text>
            {loading && !data ? (
                <div style={{ textAlign: 'center', padding: 24 }}><Spin /></div>
            ) : versions.length === 0 ? (
                <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="No earlier versions are recorded yet. This form's history starts the next time it is published."
                />
            ) : (
                <List
                    dataSource={versions}
                    renderItem={(v) => (
                        <List.Item
                            actions={[
                                v.is_current ? null : (
                                    <Button key="restore" size="small" loading={restoring === v.version} onClick={() => onRestore(v.version)}>
                                        Restore as draft
                                    </Button>
                                ),
                            ]}
                        >
                            <List.Item.Meta
                                title={<span>Version {v.version} {v.is_current && <Tag color="green" style={{ marginInlineStart: 6 }}>Live</Tag>}</span>}
                                description={`${v.title}${v.publishedAt ? ` · published ${when(v.publishedAt)}` : ''}`}
                            />
                        </List.Item>
                    )}
                />
            )}
        </Modal>
    );
};

export default VersionHistoryModal;
