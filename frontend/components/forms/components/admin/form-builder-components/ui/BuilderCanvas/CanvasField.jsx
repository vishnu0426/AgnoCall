import React from 'react';
import { Button, Space, Tag, Typography, theme as antdTheme } from 'antd';
import { GripVertical, Copy, Trash2 } from 'lucide-react';
import { FieldPreview } from '../FieldPreviews/renderFieldPreview.jsx';
import { isScorableField } from '../../constants/fieldDefaults.js';

const { Text } = Typography;

const CanvasField = ({
    field, index, isSelected, onSelect, onUpdate, hasScoring = false,
    onDelete, onDuplicate, onDragStart, onDragOver, onDrop
}) => {
    const { token } = antdTheme.useToken();

    return (
        <div
            className={`canvas-field-card ${isSelected ? 'selected' : ''}`}
            onClick={onSelect}
            onDragOver={onDragOver}
            onDrop={onDrop}
            style={{
                border: isSelected ? `2px solid ${token.colorPrimary}` : `1px solid ${token.colorBorderSecondary}`,
                borderLeft: field.type === 'section' ? `4px solid ${token.colorPrimary}` : undefined,
                borderRadius: '12px',
                padding: field.type === 'section' ? '12px 16px' : '16px',
                marginBottom: '12px',
                background: field.type === 'section' ? token.colorPrimaryBg : token.colorBgContainer,
                cursor: 'pointer',
                transition: 'all 0.2s ease',
            }}
        >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1 }}>
                    <div
                        draggable
                        onDragStart={onDragStart}
                        style={{ cursor: 'grab', color: token.colorTextSecondary }}
                    >
                        <GripVertical size={16} />
                    </div>
                    <div style={{ flex: 1 }}>
                        <Text strong style={{ fontSize: field.type === 'section' ? '15px' : '14px' }}>
                            {field.label}
                        </Text>
                        {field.type === 'section' && <Tag style={{ marginInlineStart: 8, marginInlineEnd: 0 }}>Section</Tag>}
                        {hasScoring && isScorableField(field.type) && (
                            <Tag color="blue" style={{ marginInlineStart: 8, marginInlineEnd: 0 }}>{Number(field.max_score) || 0} pts</Tag>
                        )}
                        {field.required && <Tag color="red" style={{ marginInlineStart: 6, marginInlineEnd: 0 }}>Required</Tag>}
                        {field.critical && (
                            <Tag color="volcano" style={{ marginInlineStart: 6, marginInlineEnd: 0 }} title="If this answer earns 0 points, the whole form scores 0">
                                Critical
                            </Tag>
                        )}
                        {field.description && (
                            <Text type="secondary" style={{ fontSize: '12px', display: 'block' }}>
                                {field.description}
                            </Text>
                        )}
                    </div>
                </div>
                <Space size="4">
                    <Button
                        type="text"
                        size="small"
                        icon={<Copy size={14} />}
                        onClick={(e) => { e.stopPropagation(); onDuplicate(); }}
                    />
                    <Button
                        type="text"
                        size="small"
                        danger
                        icon={<Trash2 size={14} />}
                        onClick={(e) => { e.stopPropagation(); onDelete(); }}
                    />
                </Space>
            </div>
            {field.type !== 'section' && (
                <div style={{ marginTop: '12px' }}>
                    <FieldPreview field={field} isPreview={false} />
                </div>
            )}
        </div>
    );
};

export default CanvasField;
