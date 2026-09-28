import { sqliteTable, text, integer, index } from 'drizzle-orm/sqlite-core';
export const jobs = sqliteTable('jobs', {
 id:text('id').primaryKey(), owner:text('owner').notNull(), filename:text('filename').notNull(),
 bytes:integer('bytes').notNull(), createdAt:text('created_at').notNull(), settings:text('settings').notNull(),
 record:text('record').notNull(), upstreamId:text('upstream_id'),
}, table => [index('jobs_owner_created').on(table.owner,table.createdAt)]);
