import React, { useMemo, useState } from 'react';
import { Input, Typography, theme as antdTheme } from 'antd';
import { Search } from 'lucide-react';
import PaletteItem from './PaletteItem.jsx';
import { FIELD_TYPES, FIELD_CATEGORIES } from '../../constants/fieldTypes.js';

const { Text } = Typography;

const FieldPalette = ({ onDragStart, onAddField }) => {
    const { token } = antdTheme.useToken();
    const [query, setQuery] = useState('');
    const q = query.trim().toLowerCase();
    const matches = useMemo(
        () => FIELD_TYPES.filter((f) => !q || f.label.toLowerCase().includes(q) || f.description.toLowerCase().includes(q)),
        [q]
    );

    return (
        <div className="builder-sidebar field-palette-sidebar" style={{
            background: token.colorBgContainer,
            borderRight: `1px solid ${token.colorBorderSecondary}`,
            overflow: 'auto',
        }}>
            <div className="sidebar-header" style={{ borderBottom: `1px solid ${token.colorBorderSecondary}`, gap: 8 }}>
                <Text strong style={{ fontSize: 14, whiteSpace: 'nowrap' }}>Add a field</Text>
                <Input
                    allowClear
                    size="small"
                    style={{ maxWidth: 104 }}
                    prefix={<Search size={13} style={{ color: token.colorTextSecondary }} />}
                    placeholder="Search"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                />
            </div>
            <div className="sidebar-content">
                {FIELD_CATEGORIES.map((category) => {
                    const items = matches.filter((f) => f.category === category.id);
                    if (items.length === 0) return null;
                    return (
                        <div key={category.id} style={{ marginBottom: 16 }}>
                            <Text type="secondary" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.5px', display: 'block', marginBottom: 6, padding: '0 2px' }}>
                                {category.label}
                            </Text>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 6 }}>
                                {items.map((fieldType) => (
                                    <PaletteItem key={fieldType.type} fieldType={fieldType} onDragStart={onDragStart} onAdd={onAddField} />
                                ))}
                            </div>
                        </div>
                    );
                })}
                {matches.length === 0 && <Text type="secondary" style={{ fontSize: 12.5 }}>No field type matches "{query}".</Text>}
            </div>
        </div>
    );
};

export default FieldPalette;
