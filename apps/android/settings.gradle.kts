pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }
dependencyResolutionManagement { repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS); repositories { google(); mavenCentral() } }
rootProject.name = "SmartScan"
include(":app")
include(":core:auth")
include(":core:model")
include(":core:network")
include(":core:security")
include(":data:local")
include(":data:repository")
include(":feature:capture")

