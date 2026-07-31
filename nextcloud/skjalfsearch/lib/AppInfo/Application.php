<?php

declare(strict_types=1);

/**
 * @copyright Copyright (c) 2024 Skjalf Team
 *
 * @author Skjalf Team
 *
 * @license AGPL-3.0-or-later
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as
 * published by the Free Software Foundation, either version 3 of the
 * License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

namespace OCA\Skjalfsearch\AppInfo;

use OCP\App\IAppManager;
use OCP\AppFramework\App;
use OCP\AppFramework\Bootstrap\IBootContext;
use OCP\AppFramework\Bootstrap\IBootstrap;
use OCP\AppFramework\Bootstrap\IRegistrationContext;
use OCA\Skjalfsearch\Listener\FileChangedListener;
use OCA\Skjalfsearch\Listener\NodeChangedListener;

class Application extends App implements IBootstrap {
	public const APP_NAME = 'skjalfsearch';

	public function __construct() {
		parent::__construct(self::APP_NAME);
	}

	public function register(IRegistrationContext $context): void {
		// Register event listeners for file system changes
		$context->registerEventListener(\OCP\Files\Events\Node::class, FileChangedListener::class);
		$context->registerEventListener(\OCP\Files\Events\Node::class, NodeChangedListener::class);
	}

	public function boot(IBootContext $context): void {
		// No bootstrapping needed at this time
	}
}
