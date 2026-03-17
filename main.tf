terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = "the-other-side-489308"
  region  = "us-central1"
}

# 1. GCS Bucket for Videos
resource "google_storage_bucket" "video_bucket" {
  name          = "the-other-side-489308-tos-videos"
  location      = "US-CENTRAL1"
  force_destroy = true
  uniform_bucket_level_access = true
}

# 2. Public Access for Video Viewing
resource "google_storage_bucket_iam_binding" "public_rule" {
  bucket = google_storage_bucket.video_bucket.name
  role   = "roles/storage.objectViewer"
  members = ["allUsers"]
}

# 3. Firestore Database (For ADK Session persistence if needed later)
resource "google_firestore_database" "database" {
  name        = "(default)"
  location_id = "us-central1"
  type        = "FIRESTORE_NATIVE"
}

# 4. Service Account
resource "google_service_account" "sa" {
  account_id   = "the-other-side-sa"
  display_name = "The Other Side Service Account"
}

# 5. Roles required for ADK and Gemini
resource "google_project_iam_member" "sa_roles" {
  for_each = toset([
    "roles/aiplatform.user",
    "roles/texttospeech.client",
    "roles/storage.objectAdmin",
    "roles/datastore.user",
    "roles/cloudvision.admin"
  ])
  project = "the-other-side-489308"
  role    = each.key
  member  = "serviceAccount:${google_service_account.sa.email}"
}
