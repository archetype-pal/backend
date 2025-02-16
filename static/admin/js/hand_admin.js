// static/js/hand_admin.js
document.addEventListener('DOMContentLoaded', function() {
    function updateItemPartImages() {
        var itemPartId = document.getElementById('id_item_part').value;
        var imagesSelectFrom = document.getElementById('id_item_part_images_from');
        var imagesSelectTo = document.getElementById('id_item_part_images_to');

        if (itemPartId) {
            // Fetch images for the selected item_part
            fetch('/api/v1/admin/get_item_images/?item_part_id=' + itemPartId)
                .then(response => response.json())
                .then(data => {
                    // Clear existing options
                    imagesSelectFrom.innerHTML = '';
                    imagesSelectTo.innerHTML = '';
                    // Add new options to "Available" pane
                    data.images.forEach(function(image) {
                        var option = new Option(image.text, image.id);
                        imagesSelectFrom.appendChild(option);
                    });
                });
        } else {
            // Clear options if no item_part selected
            imagesSelectFrom.innerHTML = '';
            imagesSelectTo.innerHTML = '';
        }
    }

    // Listen for changes in item_part
    document.getElementById('id_item_part').addEventListener('change', updateItemPartImages);
    // Initial update if editing an existing Hand
    updateItemPartImages();
});