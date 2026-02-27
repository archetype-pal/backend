"""
This widget was created with AI. Its goal is to provide a popup
in the management UI that lists folders and files in the MEDIA
folder to choose from.
"""

from django.forms import widgets
from django.utils.safestring import mark_safe


class ImagePickerWidget(widgets.TextInput):
    def render(self, name, value, attrs=None, renderer=None):
        html = super().render(name, value, attrs, renderer)

        # Button to open the popup
        button_html = """
        <button type="button" class="image-picker-button" onclick="openImagePickerPopup()"
          style="padding: 8px 12px; background: #007bff; color: white; border: none; 
          border-radius: 4px; cursor: pointer;">

            <i class="fas fa-image"></i> Choose Image
        </button>
        """

        # HTML for the popup
        popup_html = """
        <div id="imagePickerPopup" style="display: none; position: fixed;
          top: 50%; left: 50%; transform: translate(-50%, -50%); background: white;
          padding: 20px; border: 1px solid #ddd; border-radius: 8px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
          z-index: 1000; width: 80%; max-width: 800px; max-height: 80vh; overflow-y: auto;">

            <h3 style="margin-top: 0; font-size: 18px; color: #333;">
                <i class="fas fa-folder-open"></i> Select an Image
            </h3>
            <div id="imagePickerBreadcrumbs" style="margin-bottom: 20px; font-size: 14px; color: #666;">
                <span class="breadcrumb" data-path="" style="cursor: pointer; padding: 4px 8px; border-radius: 4px;
                  background: #f1f1f1;">
                    <i class="fas fa-home"></i> Home
                </span>
            </div>
            <div id="imagePickerContent" style="display: grid; 
              grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 15px;">
                <!-- Content will be loaded dynamically -->
            </div>
            <button type="button" onclick="closeImagePickerPopup()" style="margin-top: 20px; padding: 8px 12px;
              background: #dc3545; color: white; border: none; border-radius: 4px; cursor: pointer;">
                <i class="fas fa-times"></i> Close
            </button>
        </div>
        """

        # JavaScript to handle the popup, folder navigation, and image selection
        js = """
        <script>
        function openImagePickerPopup() {{
            document.getElementById('imagePickerPopup').style.display = 'block';
            loadFolderContent('');
        }}

        function closeImagePickerPopup() {{
            document.getElementById('imagePickerPopup').style.display = 'none';
        }}

        function loadFolderContent(folderPath) {{
            fetch(`/api/v1/manuscripts/management/image-picker-content/?path=${{encodeURIComponent(folderPath)}}`)
                .then(response => response.json())
                .then(data => {{
                    const contentDiv = document.getElementById('imagePickerContent');
                    contentDiv.innerHTML = '';

                    data.folders.forEach(folder => {{
                        const folderElement = document.createElement('div');
                        folderElement.className = 'picker-item';
                        folderElement.innerHTML = `
                            <div style="text-align: center; cursor: pointer;">
                                <i class="fas fa-folder" style="font-size: 64px; color: #ffc107;"></i>
                                <div style="margin-top: 8px; font-size: 14px; color: #555; word-wrap: break-word;">
                                  ${{folder.name}}</div>
                            </div>
                        `;
                        folderElement.addEventListener('click', () => loadFolderContent(folder.path));
                        contentDiv.appendChild(folderElement);
                    }});

                    data.images.forEach(image => {{
                        const imageElement = document.createElement('div');
                        imageElement.className = 'picker-item';
                        imageElement.innerHTML = `
                            <div style="text-align: center; cursor: pointer;">
                                <img src="${{image.url}}" alt="${{image.name}}" style="max-width: 150px;
                                  max-height: 150px; border-radius: 4px; border: 1px solid #ddd;">
                                <div style="margin-top: 8px; font-size: 14px; color: #555; word-wrap: break-word;">
                                  ${{image.name}}</div>
                            </div>
                        `;
                        imageElement.addEventListener('click', () => {{
                            document.getElementById('{}').value = image.path;
                            closeImagePickerPopup();
                        }});
                        contentDiv.appendChild(imageElement);
                    }});

                    updateBreadcrumbs(folderPath);
                }});
        }}

        function updateBreadcrumbs(folderPath) {{
            const breadcrumbsDiv = document.getElementById('imagePickerBreadcrumbs');
            breadcrumbsDiv.innerHTML = '';

            const parts = folderPath.split('/').filter(part => part);
            let currentPath = '';

            breadcrumbsDiv.appendChild(createBreadcrumb('Home', ''));

            parts.forEach(part => {{
                currentPath += `${{part}}/`;
                breadcrumbsDiv.appendChild(createBreadcrumb(part, currentPath));
            }});
        }}

        function createBreadcrumb(name, path) {{
            const span = document.createElement('span');
            span.className = 'breadcrumb';
            span.innerHTML = `<i class="fas fa-chevron-right" style="margin: 0 8px; color: #999;"></i>${{name}}`;
            span.setAttribute('data-path', path);
            span.addEventListener('click', () => loadFolderContent(path));
            return span;
        }}
        </script>
        """.format(attrs["id"])

        return mark_safe(html + button_html + popup_html + js)
