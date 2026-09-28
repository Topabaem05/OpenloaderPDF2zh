CREATE TABLE `jobs` (
	`id` text PRIMARY KEY NOT NULL,
	`owner` text NOT NULL,
	`filename` text NOT NULL,
	`bytes` integer NOT NULL,
	`created_at` text NOT NULL,
	`settings` text NOT NULL,
	`record` text NOT NULL,
	`upstream_id` text
);
--> statement-breakpoint
CREATE INDEX `jobs_owner_created` ON `jobs` (`owner`,`created_at`);