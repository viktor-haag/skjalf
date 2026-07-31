<?php

/**
 * @copyright Copyright (c) 2024 Skjalf Team
 *
 * @author Skjalf Team
 *
 * @license AGPL-3.0-or-later
 */

$l = \OC::$server->getL10N('skjalf_search');

return [
	"app.name" => $l->t("Skjalf Search"),
	"app.description" => $l->t("AI-powered image search for Nextcloud"),
	"search.placeholder" => $l->t("Search images..."),
	"search.button" => $l->t("Search"),
	"search.loading" => $l->t("Searching..."),
	"search.results" => $l->t("Results"),
	"search.similarity" => $l->t("Similarity"),
	"folders.title" => $l->t("Registered Folders"),
	"error.search_failed" => $l->t("Search failed"),
	"error.folder_not_found" => $l->t("Folder not found"),
	"error.file_not_found" => $l->t("File not found"),
	"error.not_authenticated" => $l->t("Not authenticated"),
	"status.complete" => $l->t("Complete"),
	"status.pending" => $l->t("Pending"),
	"status.error" => $l->t("Error"),
];
