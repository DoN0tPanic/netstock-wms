import type { UserRole } from '../types/api';
export type Permission = 'read' | 'export' | 'operate' | 'manage_master_data' | 'reserve' | 'reverse' | 'adjust' | 'deactivate' | 'manage_users' | 'manage_templates' | 'view_audit';
const grants: Record<UserRole, ReadonlySet<Permission>> = { viewer: new Set(['read', 'export']), operator: new Set(['read', 'export', 'operate', 'manage_master_data', 'reserve', 'reverse']), admin: new Set(['read', 'export', 'operate', 'manage_master_data', 'reserve', 'reverse', 'adjust', 'deactivate', 'manage_users', 'manage_templates', 'view_audit']) };
export const can = (role: UserRole | undefined, permission: Permission): boolean => role ? grants[role].has(permission) : false;
