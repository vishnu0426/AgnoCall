import React, { useMemo, useState } from 'react';
import { Button, Input, Tooltip, Typography, Space, Empty, Spin, theme as antdTheme } from 'antd';
import { FolderOpen, Plus, Search } from 'lucide-react';
import FormCard from './FormCard.jsx';

const { Title, Text } = Typography;

const FormsLibrary = ({ forms, selectedForm, onSelectForm, onDelete, onDuplicate, onCreate, loading }) => {
    const { token } = antdTheme.useToken();
    const [query, setQuery] = useState('');
    const shown = useMemo(() => {
        const q = query.trim().toLowerCase();
        return (forms || []).filter((f) => !q || (f.title || '').toLowerCase().includes(q));
    }, [forms, query]);

    if (loading && !forms) {
        return (
            <div className="builder-sidebar forms-library-sidebar" style={{ background: token.colorBgContainer, padding: '40px', justifyContent: 'center', alignItems: 'center' }}>
                <Spin size="large" />
            </div>
        );
    }
    return (
        <div className="builder-sidebar forms-library-sidebar" style={{ background: token.colorBgContainer, borderRight: `1px solid ${token.colorBorderSecondary}` }}>
            <div className="sidebar-header" style={{ borderBottom: `1px solid ${token.colorBorderSecondary}` }}>
                <Space>
                    <FolderOpen size={18} style={{ color: token.colorPrimary }} />
                    <Title level={5} style={{ margin: 0, fontSize: 15 }}>Forms</Title>
                    <Text type="secondary" style={{ fontSize: 12 }}>{(forms || []).length}</Text>
                </Space>
                <Tooltip title="Create a new form">
                    <Button type="primary" shape="circle" size="small" aria-label="Create a new form" icon={<Plus size={14} />} onClick={onCreate} />
                </Tooltip>
            </div>
            {(forms || []).length > 3 && (
                <div style={{ padding: '10px 12px 0' }}>
                    <Input
                        allowClear
                        size="small"
                        prefix={<Search size={13} style={{ color: token.colorTextSecondary }} />}
                        placeholder="Search forms"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                    />
                </div>
            )}
            <div className="sidebar-content">
                {shown.map((form) => (
                    <FormCard key={form.id} form={form} isSelected={selectedForm?.id === form.id} onSelect={onSelectForm} onDelete={onDelete} onDuplicate={onDuplicate} />
                ))}
                {shown.length === 0 && (
                    <Empty
                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                        description={<Text type="secondary">{query ? 'No form matches your search' : 'No forms yet. Create one with +'}</Text>}
                        style={{ marginTop: 40 }}
                    />
                )}
            </div>
        </div>
    );
};

export default FormsLibrary;
