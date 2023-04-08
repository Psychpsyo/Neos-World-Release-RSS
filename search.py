import datetime
import requests
import socketserver
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs
from xml.dom import minidom

# TODO: Switch back to api.neos.com once that SSL cert gets renewed
NEOS_API = "https://cloudx.azurewebsites.net/"
NEOS_ASSET_ENDPOINT = "https://assets.neos.com/assets/"
FEED_LINK = "https://feed.neos.love/atom.xml"
feed_cache = {}
featured_feed_cache = {}

#raised by the server code to have it return 400 instead of 500.
class ClientException(Exception):
	pass

def getFeed(page = 1, featuredOnly = False):
	cache = (featured_feed_cache if featuredOnly else feed_cache)
	# if page was cached within the last 30 minutes
	if page in cache and (datetime.datetime.now() - cache[page]["lastUpdated"]).total_seconds() < 60 * 30:
		return cache[page]["feedString"]
	
	worldResponse = requests.post(
		NEOS_API + "api/records/pagedSearch",
		json = {
			"count": 50,
			"offset": (page - 1) * 50,
			"private": False,
			"onlyFeatured": featuredOnly,
			"recordType": "world",
			"sortBy": "FirstPublishTime",
			"sortDirection": "Descending"
		}
	)
	
	# On Neos server error, serve from cache if you can
	if worldResponse.status_code != 200:
		print("Failed to request updated Neos sessions!")
		return cache.get(page, {"feedString": ""})["feedString"]
	
	# otherwise regenerate the feed
	
	worldList = worldResponse.json()["records"]
	atomNow = datetime.datetime.now(datetime.timezone.utc).isoformat()
	xmlString = ""
	
	with minidom.parse("templateFeed.xml") as atomFeed:
		atomFeed.getElementsByTagName("title").item(0).firstChild.data = "Featured Neos Worlds" if featuredOnly else "Published Neos Worlds"
		atomFeed.getElementsByTagName("id").item(0).firstChild.data = "https://feed.neos.love/atom.xml?featuredOnly=true" if featuredOnly else "https://feed.neos.love/atom.xml"

		atomFeed.getElementsByTagName("updated").item(0).appendChild(atomFeed.createTextNode(atomNow))
		feed = atomFeed.getElementsByTagName("feed").item(0)

		linkSelf = atomFeed.createElement("link")
		linkSelf.setAttribute("rel", "self")
		linkSelf.appendChild(atomFeed.createTextNode(FEED_LINK + "?" + ("featuredOnly=true&" if featuredOnly else "") + "page=" + str(page)))
		feed.appendChild(linkSelf)

		linkFirst = atomFeed.createElement("link")
		linkFirst.setAttribute("rel", "first")
		linkFirst.appendChild(atomFeed.createTextNode(FEED_LINK + ("?featuredOnly=true" if featuredOnly else "")))
		feed.appendChild(linkFirst)

		if page > 1:
			linkPrev = atomFeed.createElement("link")
			linkPrev.setAttribute("rel", "previous")
			linkPrev.appendChild(atomFeed.createTextNode(FEED_LINK + "?" + ("featuredOnly=true&" if featuredOnly else "") + ("page=" + str(page - 1)))
			feed.appendChild(linkPrev)

		linkNext = atomFeed.createElement("link")
		linkNext.setAttribute("rel", "next")
		linkNext.appendChild(atomFeed.createTextNode(FEED_LINK + "?" + ("featuredOnly=true&" if featuredOnly else "") + ("page=" + str(page + 1)))
		feed.appendChild(linkNext)

		for world in worldList:
			entry = atomFeed.createElement("entry")

			id = atomFeed.createElement("id")
			id.appendChild(atomFeed.createTextNode("https://cloudx.azurewebsites.net/open/world/" + world["ownerId"] + "/" + world["id"]))
			entry.appendChild(id)

			title = atomFeed.createElement("title")
			title.appendChild(atomFeed.createTextNode(world["ownerName"] + " published " + world["name"]))
			entry.appendChild(title)

			if "description" in world:
				summary = atomFeed.createElement("summary")
				summary.appendChild(atomFeed.createTextNode(world["description"]))
				entry.appendChild(summary)

			content = atomFeed.createElement("content")
			content.setAttribute("src", NEOS_ASSET_ENDPOINT + world["thumbnailUri"][10:-5])
			content.setAttribute("type", "image/webp")
			entry.appendChild(content)

			author = atomFeed.createElement("author")
			authorName = atomFeed.createElement("name")
			authorName.appendChild(atomFeed.createTextNode(world["ownerName"]))
			author.appendChild(authorName)
			authorId = atomFeed.createElement("neos:userId")
			authorId.appendChild(atomFeed.createTextNode(world["ownerId"]))
			author.appendChild(authorId)
			entry.appendChild(author)

			category = atomFeed.createElement("category")
			category.setAttribute("term", "Games/NeosVR/Worlds")
			category.setAttribute("label", "NeosVR Worlds")
			entry.appendChild(category)

			link = atomFeed.createElement("link")
			link.setAttribute("rel", "alternate")
			link.setAttribute("href", "https://cloudx.azurewebsites.net/open/world/" + world["ownerId"] + "/" + world["id"])
			entry.appendChild(link)

			published = atomFeed.createElement("published")
			published.appendChild(atomFeed.createTextNode(world["firstPublishTime"]))
			entry.appendChild(published)

			updated = atomFeed.createElement("updated")
			updated.appendChild(atomFeed.createTextNode(world["lastModificationTime"]))
			entry.appendChild(updated)

			recordId = atomFeed.createElement("neos:recordId")
			recordId.appendChild(atomFeed.createTextNode(world["id"]))
			entry.appendChild(recordId)

			visits = atomFeed.createElement("neos:worldVisits")
			visits.appendChild(atomFeed.createTextNode(str(world["visits"])))
			entry.appendChild(visits)

			thumbnail = atomFeed.createElement("neos:worldThumbnail")
			thumbnailUri = atomFeed.createElement("uri")
			thumbnailUri.appendChild(atomFeed.createTextNode(world["thumbnailUri"]))
			thumbnail.appendChild(thumbnailUri)
			entry.appendChild(thumbnail)

			tags = atomFeed.createElement("neos:tags")
			for tagString in world["tags"]:
				tag = atomFeed.createElement("neos:tag")
				tag.appendChild(atomFeed.createTextNode(tagString))
				tags.appendChild(tag)
			entry.appendChild(tags)

			feed.appendChild(entry)

		xmlString = atomFeed.toprettyxml(encoding="utf-8", standalone=True).decode("utf-8")
		xmlString = "\n".join([line for line in xmlString.splitlines() if line.strip()])
	
	cache[page] = {
		"lastUpdated": datetime.datetime.now(),
		"feedString": xmlString
	}
	return cache[page]["feedString"]



class HttpHandler(BaseHTTPRequestHandler):
	def do_GET(self):
		try:
			query = parse_qs(self.path[2:])
			page = int(query.get("page", ["1"])[0])
			featuredOnly = query.get("featuredOnly", ["false"])[0] == "true"

			if (page < 1):
				raise ClientException()

			feed = getFeed(page, featuredOnly)
			if feed == "":
				self.send_response(404)
				self.send_header("Access-Control-Allow-Origin", "*")
				self.end_headers()
				return

			self.send_response(200)
			self.send_header("Content-type", "application/xml")
			self.send_header("Access-Control-Allow-Origin", "*")
			self.send_header("Cache-Control", "max-age=86400, stale-while-revalidate=31536000")
			self.end_headers()
			self.wfile.write(bytes(feed, "utf-8"))
		except ClientException: # The client made a mistake, send 400 Bad Request
			self.send_response(400)
			self.send_header("Access-Control-Allow-Origin", "*")
			self.end_headers()
		except Exception as e: # Something else went wrong, send 500 Internal Server Error
			raise e
			self.send_response(500)
			self.send_header("Access-Control-Allow-Origin", "*")
			self.end_headers()

httpd = socketserver.TCPServer(("localhost", 9305), HttpHandler)
httpd.serve_forever()